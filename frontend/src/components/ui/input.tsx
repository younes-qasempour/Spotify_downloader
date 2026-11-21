import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  leadingIcon?: React.ReactNode;
  trailingSlot?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, leadingIcon, trailingSlot, ...props }, ref) => {
    if (!leadingIcon && !trailingSlot) {
      return (
        <input
          ref={ref}
          className={cn(
            "flex h-10 w-full rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 transition-colors focus:border-emerald-500/60 focus:bg-white/[0.06] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            className
          )}
          {...props}
        />
      );
    }

    return (
      <div className="relative flex w-full items-center">
        {leadingIcon && (
          <div className="pointer-events-none absolute left-3.5 text-zinc-400">
            {leadingIcon}
          </div>
        )}
        <input
          ref={ref}
          className={cn(
            "flex h-10 w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 text-sm text-zinc-100 placeholder:text-zinc-500 transition-colors focus:border-emerald-500/60 focus:bg-white/[0.06] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            leadingIcon ? "pl-10" : "pl-3.5",
            trailingSlot ? "pr-24" : "pr-3.5",
            className
          )}
          {...props}
        />
        {trailingSlot && (
          <div className="absolute right-1.5 flex items-center gap-1">
            {trailingSlot}
          </div>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
