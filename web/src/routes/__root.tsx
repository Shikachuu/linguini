import { createRootRouteWithContext, Outlet } from "@tanstack/react-router"
import { ThemeProvider } from "next-themes"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { RouterContext } from "@/router"

const Root = () => {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <TooltipProvider>
        <Outlet />
        <Toaster position="top-center" />
      </TooltipProvider>
    </ThemeProvider>
  )
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: Root,
})
