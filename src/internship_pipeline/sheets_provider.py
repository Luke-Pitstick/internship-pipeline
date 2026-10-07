"""Google service-account authentication and bounded official Sheets v4 calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

import httpx
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
BASE = "https://sheets.googleapis.com/v4/spreadsheets/"


class SheetsFailure(ValueError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(
            {
                "revoked": "Google access revoked or spreadsheet permission denied.",
                "retry": "Google unavailable. Retry is scheduled.",
                "invalid": "Google response or destination is invalid.",
                "uncertain": "Write acknowledgement unknown; next attempt reads before writing.",
            }[status]
        )


def credential_info(text: str) -> dict[str, Any]:
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError
        if (
            raw.get("type") != "service_account"
            or raw.get("token_uri") != TOKEN_URI
            or raw.get("universe_domain", "googleapis.com") != "googleapis.com"
            or not raw["client_email"].endswith(".iam.gserviceaccount.com")
        ):
            raise ValueError
        # Never honor arbitrary credential endpoints, delegation or external-account URLs.
        info = {
            key: raw[key]
            for key in (
                "type",
                "project_id",
                "private_key_id",
                "private_key",
                "client_email",
                "token_uri",
            )
        }
        create_credentials = cast(
            Callable[..., service_account.Credentials],
            service_account.Credentials.from_service_account_info,
        )
        create_credentials(info, scopes=[SCOPE])
        return info
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError(
            "Enter a valid Google service-account JSON key using the official token endpoint."
        ) from None


class GoogleSheets:
    def __init__(self, info: dict[str, Any], spreadsheet_id: str, *, transport: Any = None):
        self.spreadsheet_id = spreadsheet_id
        self.client = httpx.Client(
            transport=transport, timeout=20, follow_redirects=False, trust_env=False
        )
        create_credentials = cast(
            Callable[..., service_account.Credentials],
            service_account.Credentials.from_service_account_info,
        )
        self.credentials = create_credentials(info, scopes=[SCOPE])

    def close(self) -> None:
        self.client.close()

    def _auth_request(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        if url != TOKEN_URI:
            raise SheetsFailure("invalid")
        response = self.client.request(method, url, content=body, headers=headers)
        if response.status_code == 429 or response.status_code >= 500:
            raise SheetsFailure("retry")
        return SimpleNamespace(
            status=response.status_code, data=response.content, headers=response.headers
        )

    def call(
        self,
        suffix: str = "",
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            if not self.credentials.valid:
                refresh = cast(Callable[[Callable[..., Any]], None], self.credentials.refresh)
                refresh(self._auth_request)
            response = self.client.request(
                "GET" if body is None else "POST",
                BASE + self.spreadsheet_id + suffix,
                headers={"Authorization": "Bearer " + cast(str, self.credentials.token)},
                json=body,
                params=params,
            )
        except GoogleAuthError:
            raise SheetsFailure("revoked") from None
        except httpx.HTTPError:
            raise SheetsFailure("uncertain" if body is not None else "retry") from None
        if response.status_code in {401, 403}:
            raise SheetsFailure("revoked")
        if response.status_code == 429 or response.status_code >= 500:
            raise SheetsFailure("retry")
        if response.status_code != 200 or len(response.content) > 10_000_000:
            raise SheetsFailure("invalid")
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except ValueError:
            raise SheetsFailure("invalid") from None

    def metadata(self) -> dict[str, Any]:
        return self.call(
            params={
                "fields": (
                    "spreadsheetId,properties(title),"
                    "sheets(properties(sheetId,title,gridProperties))"
                )
            }
        )

    def rows(self, title: str) -> list[list[Any]]:
        escaped = "'" + title.replace("'", "''") + "'!A1:AZ10001"
        result = self.call(
            "/values/" + quote(escaped, safe=""), params={"valueRenderOption": "FORMULA"}
        )
        rows = result.get("values", [])
        if (
            not isinstance(rows, list)
            or len(rows) > 10001
            or any(
                not isinstance(row, list)
                or len(row) > 52
                or any(not isinstance(value, (str, int, float, bool)) for value in row)
                for row in rows
            )
        ):
            raise SheetsFailure("invalid")
        return rows

    def formulas(self, title: str) -> set[tuple[int, str]]:
        escaped = "'" + title.replace("'", "''") + "'!A1:AZ10001"
        result = self.call(
            params={
                "ranges": escaped,
                "includeGridData": "true",
                "fields": (
                    "sheets(data(startRow,startColumn,"
                    "rowData(values(userEnteredValue(formulaValue)))))"
                ),
            }
        )
        output = set()
        for sheet in result.get("sheets", []):
            for grid in sheet.get("data", []):
                for offset, row in enumerate(grid.get("rowData", [])):
                    for index, value in enumerate(row.get("values", [])):
                        if value.get("userEnteredValue", {}).get("formulaValue") is not None:
                            number = grid.get("startColumn", 0) + index + 1
                            column = ""
                            while number:
                                number, remainder = divmod(number - 1, 26)
                                column = chr(65 + remainder) + column
                            output.add((grid.get("startRow", 0) + offset + 1, column))
        return output

    def write(self, title: str, row: int, cells: dict[str, Any]) -> None:
        prefix = "'" + title.replace("'", "''") + "'!"
        self.call(
            "/values:batchUpdate",
            body={
                "valueInputOption": "RAW",
                "data": [
                    {"range": f"{prefix}{column}{row}", "values": [[value]]}
                    for column, value in cells.items()
                ],
            },
        )
