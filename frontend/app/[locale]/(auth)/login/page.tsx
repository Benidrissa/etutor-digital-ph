import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import Link from "next/link";

interface LoginPageProps {
  params: {
    locale: string;
  };
}

export default async function LoginPage({ params }: LoginPageProps) {
  const t = await getTranslations("Auth");
  const tCommon = await getTranslations("Common");

  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">{tCommon("appName")}</CardTitle>
        <CardDescription>{t("login")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="email">
            {t("email")}
          </label>
          <input
            id="email"
            type="email"
            className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base"
            placeholder="email@example.com"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="password">
            {t("password")}
          </label>
          <input
            id="password"
            type="password"
            className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base"
          />
        </div>
        <Button className="w-full min-h-11">{t("login")}</Button>
        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-card px-2 text-muted-foreground">ou</span>
          </div>
        </div>
        <Button variant="outline" className="w-full min-h-11">
          {t("withGoogle")}
        </Button>
        <Button variant="outline" className="w-full min-h-11">
          {t("withLinkedIn")}
        </Button>
        <div className="text-center text-sm mt-4">
          <span className="text-muted-foreground">{t("dontHaveAccount")} </span>
          <Link 
            href={`/${params.locale}/register`}
            className="font-medium text-primary hover:underline"
          >
            {t("signUp")}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
