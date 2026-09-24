import type * as React from "react"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * A styled native <select>: full keyboard and screen reader support from the browser.
 * The options get the popover colors because the open list is drawn by the browser: with a
 * transparent background, Chrome on Windows draws it white while the text keeps the page's
 * light color in dark mode, so the options were near-white on white.
 */
function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <div className="relative">
      <select
        data-slot="native-select"
        className={cn(
          "flex h-9 w-full min-w-0 appearance-none rounded-md border border-input bg-transparent py-1 pr-8 pl-3 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 [&_option]:bg-popover [&_option]:text-popover-foreground",
          className,
        )}
        {...props}
      />
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  )
}

export { NativeSelect }
