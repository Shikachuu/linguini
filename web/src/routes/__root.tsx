import { createRootRouteWithContext, Outlet } from "@tanstack/react-router"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { RouterContext } from "@/router"

const Root = () => {
  return (
    <TooltipProvider>
      <Outlet />
      <Toaster position="top-center" />
    </TooltipProvider>
  )
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: Root,
})
