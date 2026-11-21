import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 disabled:pointer-events-none disabled:opacity-45 cursor-pointer select-none",
  {
    variants: {
      variant: {
        default:
          "bg-emerald-brand text-black font-semibold hover:bg-emerald-bright shadow-[0_0_20px_-6px_rgba(29,185,84,0.65)] active:scale-[0.98]",
        secondary:
          "bg-white/8 text-zinc-100 hover:bg-white/14 border border-white/8",
        outline:
          "border border-white/12 bg-transparent text-zinc-200 hover:bg-white/6 hover:border-white/20",
        ghost: "text-zinc-300 hover:bg-white/8 hover:text-white",
        destructive:
          "bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25",
        glass:
          "bg-white/5 hover:bg-white/10 text-zinc-100 border border-white/10 backdrop-blur-md",
      },
      size: {
        sm: "h-8 px-3 text-xs rounded-md",
        md: "h-9 px-4 text-sm",
        lg: "h-10 px-5 text-sm",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
);
Button.displayName = "Button";
