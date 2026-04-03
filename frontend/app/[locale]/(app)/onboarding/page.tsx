import { OnboardingFlow } from '@/components/onboarding/onboarding-flow';

interface OnboardingPageProps {
  params: {
    locale: string;
  };
}

export default function OnboardingPage({ params }: OnboardingPageProps) {
  return <OnboardingFlow />;
}