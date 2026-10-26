import { cn } from "cn"
import type { ComponentProps } from "react"
import { APP_NAME } from "@/lib/brand"

export const LogoMark = ({ className, ...props }: ComponentProps<"svg">) => {
  const labelled = Boolean(props["aria-label"]) || props["aria-labelledby"] !== undefined

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={!labelled}
      role={labelled ? "img" : undefined}
      className={cn("size-6 shrink-0 text-primary", className)}
      {...props}
    >
      <path d="M9 2v4M12 2v4M15 2v4M12 17v5" />
      <path d="M6 9.5C6 7.6 8.7 6 12 6s6 1.6 6 3.5-2.7 3.5-6 3.5c-2.5 0-4-1-4-2.2S9.5 9 12 9s3.5.8 3.5 1.5" />
      <path d="M6 9.5v3c0 2.5 2.7 4.5 6 4.5s6-2 6-4.5v-3" />
    </svg>
  )
}

export const Wordmark = ({ className }: { className?: string }) => {
  return (
    <span className={cn("inline-flex items-center gap-2 font-heading font-semibold", className)}>
      <LogoMark className="size-[1.2em]" />
      {APP_NAME}
    </span>
  )
}
