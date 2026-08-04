import { Component, type ReactNode } from 'react'

type AppErrorBoundaryProps = Readonly<{
  children: ReactNode
}>

type AppErrorBoundaryState = Readonly<{
  hasError: boolean
}>

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <main className="grid min-h-dvh min-w-0 place-items-center bg-slate-950 px-4 py-8 text-slate-100 sm:py-10">
        <section
          className="min-w-0 w-full max-w-lg rounded-3xl border border-rose-300/25 bg-slate-900 p-5 shadow-2xl shadow-slate-950/40 sm:p-8"
          role="alert"
          aria-labelledby="startup-error-title"
        >
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-rose-300">
            Local prototype
          </p>
          <h1
            id="startup-error-title"
            className="text-2xl font-semibold tracking-tight text-white sm:text-3xl"
          >
            The interface could not start
          </h1>
          <p className="mt-4 leading-7 text-slate-300">
            Check the frontend&apos;s public API configuration, then reload the
            page. No private error details are shown here.
          </p>
          <button
            className="mt-6 min-h-11 w-full rounded-xl bg-white px-5 py-2.5 font-semibold text-slate-950 shadow-sm transition hover:bg-slate-100 sm:w-auto"
            type="button"
            onClick={() => globalThis.location.reload()}
          >
            Reload page
          </button>
        </section>
      </main>
    )
  }
}
