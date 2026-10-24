import { createFileRoute, Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"
import { useDeferredValue, useState } from "react"
import { useListRecipes } from "@/api/gen/endpoints/recipes/recipes"
import { PageHeader } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"

const Recipes = () => {
  const { hid } = Route.useParams()
  const [search, setSearch] = useState("")
  const q = useDeferredValue(search.trim())
  const recipes = useListRecipes(hid, q ? { q } : undefined)

  return (
    <div className="mx-auto max-w-2xl pb-6">
      <PageHeader
        title="Recipes"
        actions={
          <Button asChild size="sm">
            <Link to="/h/$hid/recipes/new" params={{ hid }}>
              <PlusIcon /> New
            </Link>
          </Button>
        }
      />
      <div className="px-4 pb-3">
        <Input
          type="search"
          placeholder="Search by title or ingredient"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
          }}
        />
      </div>
      {recipes.isPending && <Skeleton className="mx-4 h-10" />}
      {recipes.isError && <p className="px-4 text-sm text-destructive">{errorMessage(recipes.error)}</p>}
      {recipes.data?.length === 0 && (
        <p className="px-4 text-sm text-muted-foreground">
          {q ? "Nothing matches." : "No recipes yet. Add one here or ask the chat to save one."}
        </p>
      )}
      <ul className="divide-y">
        {recipes.data?.map((recipe) => (
          <li key={recipe.id}>
            <Link
              to="/h/$hid/recipes/$rid"
              params={{ hid, rid: recipe.id }}
              className="flex items-center gap-2 px-4 py-3 hover:bg-accent"
            >
              <span className="min-w-0 flex-1 truncate">{recipe.title}</span>
              <span className="text-xs text-muted-foreground">{recipe.servings} servings</span>
              {recipe.source === "chat" && <Badge variant="secondary">from chat</Badge>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/recipes/")({
  component: Recipes,
})
