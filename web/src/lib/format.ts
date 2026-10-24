const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" })
const date = new Intl.DateTimeFormat("en", { dateStyle: "medium" })
const number = new Intl.NumberFormat("en", { maximumFractionDigits: 2 })

export function formatDateTime(value: string): string {
  return dateTime.format(new Date(value))
}

export function formatDate(value: string): string {
  return date.format(new Date(value))
}

export function formatQuantity(quantity: number, unit: string): string {
  return `${number.format(quantity)} ${unit}`
}

export function daysSince(value: string, now: Date = new Date()): number {
  return Math.floor((now.getTime() - new Date(value).getTime()) / 86_400_000)
}
