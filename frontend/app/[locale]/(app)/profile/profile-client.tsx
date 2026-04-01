"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { Upload, User as UserIcon, AlertTriangle, CheckCircle } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const fetchUserProfile = async () => {
  const response = await fetch(`${API_BASE}/api/v1/users/me`, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem("access_token")}`,
    },
  });
  if (!response.ok) throw new Error("Failed to fetch profile");
  return response.json();
};

const updateProfile = async (data: Record<string, unknown>) => {
  const response = await fetch(`${API_BASE}/api/v1/users/me`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${localStorage.getItem("access_token")}`,
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Failed to update profile");
  return response.json();
};

const uploadAvatar = async (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  
  const response = await fetch(`${API_BASE}/api/v1/users/me/avatar`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${localStorage.getItem("access_token")}`,
    },
    body: formData,
  });
  if (!response.ok) throw new Error("Failed to upload avatar");
  return response.json();
};

const profileSchema = z.object({
  name: z.string().min(1, "Name is required").max(100),
  preferred_language: z.enum(["fr", "en"]),
  country: z.string().optional(),
  professional_role: z.string().optional(),
});

type ProfileFormData = z.infer<typeof profileSchema>;

const ECOWAS_COUNTRIES = [
  { code: "BJ", name: "Benin" },
  { code: "BF", name: "Burkina Faso" },
  { code: "CV", name: "Cape Verde" },
  { code: "CI", name: "Côte d'Ivoire" },
  { code: "GM", name: "Gambia" },
  { code: "GH", name: "Ghana" },
  { code: "GN", name: "Guinea" },
  { code: "GW", name: "Guinea-Bissau" },
  { code: "LR", name: "Liberia" },
  { code: "ML", name: "Mali" },
  { code: "NE", name: "Niger" },
  { code: "NG", name: "Nigeria" },
  { code: "SN", name: "Senegal" },
  { code: "SL", name: "Sierra Leone" },
  { code: "TG", name: "Togo" },
];

const PROFESSIONAL_ROLES = [
  "doctor",
  "nurse",
  "epidemiologist",
  "biostatistician", 
  "health_data_analyst",
  "public_health_researcher",
  "health_policy_analyst",
  "community_health_worker",
  "health_program_manager",
  "student",
  "other",
];

export function ProfileClient() {
  const t = useTranslations("Profile");
  const [isEditing, setIsEditing] = useState(false);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [showRecontextAlert, setShowRecontextAlert] = useState(false);
  const queryClient = useQueryClient();

  const { data: profile, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn: fetchUserProfile,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const form = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    values: profile ? {
      name: profile.name || "",
      preferred_language: profile.preferred_language || "fr",
      country: profile.country || "",
      professional_role: profile.professional_role || "",
    } : undefined,
  });

  const updateMutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: (data) => {
      queryClient.setQueryData(["profile"], data.profile || data);
      setIsEditing(false);
      if (data.content_recontextualization_required) {
        setShowRecontextAlert(true);
      }
    },
  });

  const avatarMutation = useMutation({
    mutationFn: uploadAvatar,
    onSuccess: (data) => {
      queryClient.setQueryData(["profile"], data);
      setAvatarFile(null);
    },
  });

  const onSubmit = (data: ProfileFormData) => {
    updateMutation.mutate(data);
  };

  const handleAvatarChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (file.size > 2 * 1024 * 1024) {
        alert(t("avatarSizeError"));
        return;
      }
      if (!["image/jpeg", "image/jpg", "image/png", "image/webp"].includes(file.type)) {
        alert(t("avatarTypeError"));
        return;
      }
      setAvatarFile(file);
    }
  };

  const handleAvatarUpload = () => {
    if (avatarFile) {
      avatarMutation.mutate(avatarFile);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner />
      </div>
    );
  }

  if (!profile) {
    return (
      <Card>
        <CardContent className="py-12">
          <p className="text-center text-muted-foreground">{t("profileNotFound")}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {showRecontextAlert && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            {t("recontextualizationAlert")}
          </AlertDescription>
        </Alert>
      )}

      {/* Profile Overview Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-4">
            <div className="relative">
              <Avatar className="h-20 w-20">
                <AvatarImage src={profile.avatar_url || ""} alt={profile.name} />
                <AvatarFallback className="text-2xl">
                  <UserIcon className="h-8 w-8" />
                </AvatarFallback>
              </Avatar>
              {avatarFile && (
                <div className="absolute -bottom-2 -right-2">
                  <Button
                    size="sm"
                    onClick={handleAvatarUpload}
                    disabled={avatarMutation.isPending}
                  >
                    {avatarMutation.isPending ? <LoadingSpinner className="h-4 w-4" /> : <CheckCircle className="h-4 w-4" />}
                  </Button>
                </div>
              )}
            </div>
            <div className="flex-1">
              <h2 className="text-2xl font-bold">{profile.name}</h2>
              <p className="text-muted-foreground">{profile.email}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="secondary">{t(`levels.level${profile.current_level}`)}</Badge>
                <Badge variant="outline">{profile.preferred_language.toUpperCase()}</Badge>
                {profile.country && (
                  <Badge variant="outline">
                    {ECOWAS_COUNTRIES.find(c => c.code === profile.country)?.name || profile.country}
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Label className="text-sm font-medium text-muted-foreground">{t("joinDate")}</Label>
              <p>{new Date(profile.created_at).toLocaleDateString()}</p>
            </div>
            <div>
              <Label className="text-sm font-medium text-muted-foreground">{t("streak")}</Label>
              <p>{t("streakDays", { days: profile.streak_days })}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Avatar Upload Card */}
      <Card>
        <CardHeader>
          <CardTitle>{t("avatar")}</CardTitle>
          <CardDescription>{t("avatarDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <Input
                id="avatar"
                type="file"
                accept="image/*"
                onChange={handleAvatarChange}
                className="hidden"
              />
              <Label
                htmlFor="avatar"
                className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-muted-foreground/25 p-4 text-center hover:bg-muted/50"
              >
                <Upload className="h-4 w-4" />
                {avatarFile ? avatarFile.name : t("uploadAvatar")}
              </Label>
              {avatarFile && (
                <Button onClick={handleAvatarUpload} disabled={avatarMutation.isPending}>
                  {avatarMutation.isPending ? <LoadingSpinner className="h-4 w-4" /> : t("save")}
                </Button>
              )}
            </div>
            <p className="text-sm text-muted-foreground">{t("avatarLimits")}</p>
          </div>
        </CardContent>
      </Card>

      {/* Edit Profile Card */}
      <Card>
        <CardHeader>
          <CardTitle>{t("editProfile")}</CardTitle>
          <CardDescription>{t("editProfileDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("name")}</FormLabel>
                    <FormControl>
                      <Input {...field} disabled={!isEditing} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="preferred_language"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("language")}</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={!isEditing}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="fr">{t("languages.french")}</SelectItem>
                        <SelectItem value="en">{t("languages.english")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="country"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("country")}</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={!isEditing}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {ECOWAS_COUNTRIES.map((country) => (
                          <SelectItem key={country.code} value={country.code}>
                            {country.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="professional_role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("role")}</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={!isEditing}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {PROFESSIONAL_ROLES.map((role) => (
                          <SelectItem key={role} value={role}>
                            {t(`roles.${role}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <Separator />

              <div className="flex justify-between">
                {!isEditing ? (
                  <Button onClick={() => setIsEditing(true)} variant="outline">
                    {t("edit")}
                  </Button>
                ) : (
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setIsEditing(false);
                        form.reset();
                      }}
                    >
                      {t("cancel")}
                    </Button>
                    <Button type="submit" disabled={updateMutation.isPending}>
                      {updateMutation.isPending ? <LoadingSpinner className="h-4 w-4" /> : t("save")}
                    </Button>
                  </div>
                )}
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {/* Read-only Information */}
      <Card>
        <CardHeader>
          <CardTitle>{t("accountInfo")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Label className="text-sm font-medium text-muted-foreground">{t("email")}</Label>
              <p>{profile.email}</p>
              <p className="text-xs text-muted-foreground">{t("emailReadonly")}</p>
            </div>
            <div>
              <Label className="text-sm font-medium text-muted-foreground">{t("currentLevel")}</Label>
              <p>{t(`levels.level${profile.current_level}`)}</p>
              <p className="text-xs text-muted-foreground">{t("levelReadonly")}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}