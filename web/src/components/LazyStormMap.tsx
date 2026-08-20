import { lazy, Suspense, forwardRef } from 'react'
import type { StormMapHandle } from './StormMap'

export type { StormMapHandle } from './StormMap'

// MapLibre GL is by far the heaviest dependency in the bundle (it's the
// reason `npm run build` warned about a 976KB chunk) and neither the login
// screen nor the initial paint need it — deferring the import until the map
// actually mounts keeps it out of the critical path.
const RealStormMap = lazy(() =>
  import('./StormMap').then((m) => ({ default: m.StormMap })),
)

type StormMapProps = React.ComponentProps<typeof RealStormMap>

export const StormMap = forwardRef<StormMapHandle, StormMapProps>(function LazyStormMap(
  props,
  ref,
) {
  return (
    <Suspense fallback={<div className="map-loading">carregando mapa…</div>}>
      <RealStormMap {...props} ref={ref} />
    </Suspense>
  )
})
