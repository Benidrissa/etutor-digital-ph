import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

interface StarRatingProps {
  rating: number;
  maxStars?: number;
  size?: "sm" | "md" | "lg";
  showValue?: boolean;
  className?: string;
}

const sizeMap = {
  sm: "h-3.5 w-3.5",
  md: "h-4 w-4",
  lg: "h-5 w-5",
};

export function StarRating({
  rating,
  maxStars = 5,
  size = "md",
  showValue = false,
  className,
}: StarRatingProps) {
  const clampedRating = Math.min(maxStars, Math.max(0, rating));
  const fullStars = Math.floor(clampedRating);
  const hasHalf = clampedRating - fullStars >= 0.5;
  const starClass = sizeMap[size];

  return (
    <span
      className={cn("inline-flex items-center gap-0.5", className)}
      role="img"
      aria-label={`${clampedRating.toFixed(1)} / ${maxStars}`}
    >
      {Array.from({ length: maxStars }).map((_, i) => {
        const filled = i < fullStars;
        const half = !filled && hasHalf && i === fullStars;
        return (
          <span key={i} className="relative inline-block">
            <Star
              className={cn(starClass, "text-muted-foreground/30")}
              fill="currentColor"
              aria-hidden="true"
            />
            {(filled || half) && (
              <span
                className="absolute inset-0 overflow-hidden"
                style={{ width: half ? "50%" : "100%" }}
                aria-hidden="true"
              >
                <Star
                  className={cn(starClass, "text-amber-500")}
                  fill="currentColor"
                />
              </span>
            )}
          </span>
        );
      })}
      {showValue && (
        <span className="ml-1 text-xs font-medium text-muted-foreground">
          {clampedRating.toFixed(1)}
        </span>
      )}
    </span>
  );
}
