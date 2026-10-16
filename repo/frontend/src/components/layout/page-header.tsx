import { useEffect, type ReactNode } from "react"

type PageHeaderProps = {
  title: string
  description?: ReactNode
  /** Buttons shown on the right of the title. */
  actions?: ReactNode
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  useEffect(() => {
    document.title = `${title} · Raff`
  }, [title])

  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
