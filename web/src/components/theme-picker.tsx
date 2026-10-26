import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react"
import { useTheme } from "next-themes"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"

const THEMES = [
  { value: "system", label: "System", icon: MonitorIcon },
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
] as const

export const ThemePicker = () => {
  const { theme = "system", setTheme } = useTheme()

  return (
    <ButtonGroup aria-label="Theme">
      {THEMES.map(({ value, label, icon: Icon }) => (
        <Button
          key={value}
          variant={theme === value ? "secondary" : "outline"}
          aria-pressed={theme === value}
          onClick={() => {
            setTheme(value)
          }}
        >
          <Icon /> {label}
        </Button>
      ))}
    </ButtonGroup>
  )
}
