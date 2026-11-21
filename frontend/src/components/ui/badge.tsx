import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide border transition-colors",
  {
    variants: {
      variant: {
        default: "bg-white/8 text-zinc-200 border-white/10",
        emerald: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
        gold: "bg-amber-500/15 text-amber-300 border-amber-500/30",
        sky: "bg-sky-500/15 text-sky-300 border-sky-500/30",
        violet: "bg-violet-500/15 text-violet-300 border-violet-500/30",
        danger: "bg-red-500/15 text-red-300 border-red-500/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props} />
  );
}

export function QualityBadge({
  badge,
  sourceType,
  className,
}: {
  badge?: string | null;
  sourceType?: string | null;
  className?: string;
}) {
  const upper = (badge || "").toUpperCase();
  let variant: BadgeProps["variant"] = "default";
  if (upper.includes("24")) {
    variant = "gold";
  } else if (upper.includes("FLAC")) {
    variant = "emerald";
  } else if (upper.includes("320") || upper.includes("MP3")) {
    variant = "sky";
  } else if (upper.includes("OPUS") || upper.includes("YTM")) {
    variant = "violet";
  }

  return (
    <Badge
      variant={variant}
      className={cn("font-mono uppercase text-[10px] py-0.5 px-2", className)}
      title={sourceType ? `Source: ${sourceType}` : undefined}
    >
      {badge || "AUDIO"}
    </Badge>
  );
}
