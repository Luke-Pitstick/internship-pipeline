import pytest

from internship_pipeline.internships import is_internship


@pytest.mark.parametrize(
    "title,description",
    [
        ("Software Engineering Intern", "Full-time, 40 hours per week."),
        ("Software Engineering – Summer 2027 Internships", ""),
        ("Product Manager Intern", "Build a roadmap."),
        ("Data Science Co-op", "Work on models."),
        ("Engineering Co‑op", ""),
        ("Summer Analyst", "The Internship Program offers a ten-week placement."),
        ("Student Software Developer", "This position is a paid internship."),
        ("Research Assistant", "<p>Job level: <strong>Internship</strong></p>"),
        ("Software Developer", "We are looking for a software engineering intern."),
    ],
)
def test_explicit_internship_or_coop_scope(title, description):
    assert is_internship(title, description)


@pytest.mark.parametrize(
    "title,description",
    [
        ("Senior Software Engineer", "Five years of non-internship experience required."),
        ("International Product Manager", "Own our roadmap."),
        ("Internship Program Manager", "Manage our interns."),
        ("Intern Recruiter", "Recruit engineering interns."),
        ("Software Engineer (Non-Internship)", "Permanent role."),
        ("Machine Learning Engineer Graduate - 2027 Start", "Internship experience preferred."),
        ("Software Engineer", "Mentor interns in our internship program."),
        ("Physician", "Completion of a medical internship is required."),
        ("Educational Clinician / Tutor", "Internship credits may be available."),
        ("Contract Student Worker", "This is not an internship."),
        ("Intern", "This position is not an internship."),
        ("Software Engineer", "Benefits do not apply to internship roles."),
        ("Software Engineer", ""),
    ],
)
def test_search_terms_past_experience_and_staff_roles_do_not_establish_scope(title, description):
    assert not is_internship(title, description)
