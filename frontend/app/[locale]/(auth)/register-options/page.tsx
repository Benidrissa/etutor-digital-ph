import { getTranslations } from 'next-intl/server';
import { RegisterOptionsClient } from './register-options-client';

export default async function RegisterOptionsPage() {
  const t = await getTranslations('Auth');
  const tCommon = await getTranslations('Common');

  return (
    <RegisterOptionsClient
      appName={tCommon('appName')}
      chooseVerificationMethod={t('chooseVerificationMethod')}
      emailVerification={t('emailVerification')}
      emailVerificationDesc={t('emailVerificationDesc')}
      continueWithEmail={t('continueWithEmail')}
      emailVerificationBenefits={t('emailVerificationBenefits')}
      authenticatorApp={t('authenticatorApp')}
      authenticatorAppDesc={t('authenticatorAppDesc')}
      continueWithAuthenticator={t('continueWithAuthenticator')}
      authenticatorAppBenefits={t('authenticatorAppBenefits')}
      alreadyHaveAccount={t('alreadyHaveAccount')}
      signIn={t('signIn')}
    />
  );
}
