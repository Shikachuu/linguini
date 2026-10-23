import { Link, useNavigate } from "@tanstack/react-router";
import {
  BookOpenIcon,
  ChevronsUpDownIcon,
  MessageSquareIcon,
  PackageIcon,
  PlusIcon,
  SettingsIcon,
  UserIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMe } from "@/api/gen/endpoints/auth/auth";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV = [
  { to: "/h/$hid/chat", label: "Chat", icon: MessageSquareIcon },
  { to: "/h/$hid/recipes", label: "Recipes", icon: BookOpenIcon },
  { to: "/h/$hid/inventory", label: "Pantry", icon: PackageIcon },
  { to: "/h/$hid/settings", label: "Settings", icon: SettingsIcon },
] as const;

function HouseholdSwitcher({ hid }: { hid: string }) {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const current = me?.households.find((h) => h.id === hid);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="min-w-0 justify-between gap-2 font-semibold">
          <span className="truncate">{current?.name ?? "Household"}</span>
          <ChevronsUpDownIcon className="size-4 shrink-0 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {me?.households.map((h) => (
          <DropdownMenuItem
            key={h.id}
            onSelect={() => void navigate({ to: "/h/$hid/chat", params: { hid: h.id } })}
          >
            {h.name}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: "/welcome" })}>
          <PlusIcon /> New household
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell({ hid, children }: { hid: string; children: ReactNode }) {
  return (
    <div className="flex h-dvh flex-col md:flex-row">
      <aside className="hidden w-56 shrink-0 flex-col gap-1 border-r p-3 md:flex">
        <HouseholdSwitcher hid={hid} />
        <nav className="mt-2 flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              params={{ hid }}
              className="hover:bg-accent flex items-center gap-2 rounded-md px-3 py-2 text-sm"
              activeProps={{ className: "bg-accent font-medium" }}
            >
              <Icon className="size-4" /> {label}
            </Link>
          ))}
        </nav>
        <Link
          to="/account"
          className="hover:bg-accent mt-auto flex items-center gap-2 rounded-md px-3 py-2 text-sm"
          activeProps={{ className: "bg-accent font-medium" }}
        >
          <UserIcon className="size-4" /> Account
        </Link>
      </aside>
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-2 md:hidden">
        <HouseholdSwitcher hid={hid} />
        <Button asChild variant="ghost" size="icon" aria-label="Account">
          <Link to="/account">
            <UserIcon />
          </Link>
        </Button>
      </header>
      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
      <nav className="bg-background grid h-14 shrink-0 grid-cols-4 border-t md:hidden">
        {NAV.map(({ to, label, icon: Icon }) => (
          <Link
            key={to}
            to={to}
            params={{ hid }}
            className="text-muted-foreground flex flex-col items-center justify-center gap-0.5 text-xs"
            activeProps={{ className: "text-foreground font-medium" }}
          >
            <Icon className="size-5" />
            {label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function PageHeader({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-2">
      <h1 className="truncate text-xl font-semibold">{title}</h1>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
