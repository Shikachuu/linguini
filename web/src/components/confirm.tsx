import { type ReactNode, useState } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Input } from "@/components/ui/input"

interface ConfirmProps {
  trigger: ReactNode
  title: string
  description: ReactNode
  action: string
  onConfirm: () => void
  typeToConfirm?: string
}

export function Confirm({ trigger, title, description, action, onConfirm, typeToConfirm }: ConfirmProps) {
  const [typed, setTyped] = useState("")
  return (
    <AlertDialog onOpenChange={() => setTyped("")}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {typeToConfirm && (
          <Input
            aria-label={`Type ${typeToConfirm} to confirm`}
            placeholder={typeToConfirm}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={typeToConfirm !== undefined && typed !== typeToConfirm}
            onClick={onConfirm}
          >
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
