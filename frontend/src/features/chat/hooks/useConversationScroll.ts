import { useEffect, useRef, type RefObject } from 'react'

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/** Keep the newest in-memory transcript content in view. */
export function useConversationScroll(
  updateMarker: unknown,
): RefObject<HTMLDivElement | null> {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView?.({
      block: 'end',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    })
  }, [updateMarker])

  return endRef
}
