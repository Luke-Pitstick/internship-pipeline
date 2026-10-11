import countries from 'i18n-iso-countries';
import english from 'i18n-iso-countries/langs/en.json';

countries.registerLocale(english);
export interface Choice { [key: string]: unknown; label: string; value?: string; flag?: string; search?: string; code?: string }
export const countryOptions: Choice[] = Object.entries(countries.getNames('en', {select: 'alias'}))
  .map(([code, label]) => ({
    label, value: label, code,
    flag: String.fromCodePoint(...[...code].map(letter => 127397 + letter.charCodeAt(0))),
    search: `${code} ${countries.alpha2ToAlpha3(code)} ${countries.getName(code, 'en', {select: 'all'})?.join(' ')}`
  })).sort((a, b) => a.label.localeCompare(b.label));
export const skillOptions = ['Python', 'JavaScript', 'TypeScript', 'SQL', 'Java', 'C++', 'C', 'Go', 'Rust', 'React', 'Svelte', 'Node.js', 'Git', 'Docker', 'AWS', 'PyTorch', 'TensorFlow', 'Data analysis', 'Product strategy', 'User research'].map(label => ({label}));
export const timezoneOptions = ['UTC', ...Intl.supportedValuesOf('timeZone')].map(value => ({label: value.replaceAll('_', ' '), value}));
