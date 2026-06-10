/**
 * Shared country list — the single source of truth for every country selector
 * (registration, onboarding, profile, admin course creation).
 *
 * Values are stored as ISO 3166-1 alpha-2 codes, which is the encoding the backend
 * AI prompts (lesson/flashcard/tutor) and content pipeline key on. `OWA` / `OTH` are
 * non-standard codes for the two catch-all options.
 *
 * Covers all 15 ECOWAS members (which include the 3 AES states: Mali, Burkina Faso,
 * Niger) plus "Other West African" and "Other".
 *
 * `key` indexes the `Countries` i18n namespace in messages/{fr,en}.json.
 */
export interface CountryOption {
  code: string;
  key: string;
  flag: string;
}

export const COUNTRIES: CountryOption[] = [
  { code: 'BJ', key: 'benin', flag: '🇧🇯' },
  { code: 'BF', key: 'burkina-faso', flag: '🇧🇫' },
  { code: 'CV', key: 'cabo-verde', flag: '🇨🇻' },
  { code: 'CI', key: 'cote-divoire', flag: '🇨🇮' },
  { code: 'GM', key: 'gambia', flag: '🇬🇲' },
  { code: 'GH', key: 'ghana', flag: '🇬🇭' },
  { code: 'GN', key: 'guinea', flag: '🇬🇳' },
  { code: 'GW', key: 'guinea-bissau', flag: '🇬🇼' },
  { code: 'LR', key: 'liberia', flag: '🇱🇷' },
  { code: 'ML', key: 'mali', flag: '🇲🇱' },
  { code: 'NE', key: 'niger', flag: '🇳🇪' },
  { code: 'NG', key: 'nigeria', flag: '🇳🇬' },
  { code: 'SN', key: 'senegal', flag: '🇸🇳' },
  { code: 'SL', key: 'sierra-leone', flag: '🇸🇱' },
  { code: 'TG', key: 'togo', flag: '🇹🇬' },
  { code: 'OWA', key: 'other-west-african', flag: '🌍' },
  { code: 'OTH', key: 'other', flag: '🌐' },
];
