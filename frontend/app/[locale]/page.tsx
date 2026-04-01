import { redirect } from "next/navigation";

export default function LocaleRoot({
  params,
}: {
  params: { locale: string };
}) {
  redirect(`/${params.locale}/dashboard`);
}
