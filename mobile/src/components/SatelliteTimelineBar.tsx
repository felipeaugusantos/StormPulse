import Slider from '@react-native-community/slider'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { timeAgo } from '../format'
import { colors } from '../theme'
import type { SatelliteTimeline } from '../useSatelliteTimeline'

interface Props {
  timeline: SatelliteTimeline
  /** Real (non-estimated) frame count — drives the "1 quadro · histórico em
   * formação" vs. "N quadros · 1h até a última aquisição" copy. */
  frameCount: number
}

/** Play/pause + scrubber for the satellite IR timeline (Fase 8, ADR-0091) —
 * mobile counterpart of web's `SatelliteTimelineBar.tsx`, same
 * `useSatelliteTimeline` state shape, native `Slider` instead of
 * `<input type="range">`. */
export function SatelliteTimelineBar({ timeline, frameCount }: Props) {
  const { steps, index, playing, activeStep, currentIndex, toggle, selectIndex, goLive } =
    timeline

  return (
    <View style={styles.wrap}>
      <TouchableOpacity
        style={styles.playButton}
        onPress={toggle}
        disabled={steps.length === 0}
        accessibilityLabel={
          playing
            ? 'Pausar animação'
            : steps.length === 1
              ? 'Exibir único quadro de satélite disponível'
              : 'Reproduzir última e próxima hora'
        }
      >
        <Text style={styles.playIcon}>{playing ? '⏸' : '▶'}</Text>
      </TouchableOpacity>
      <View style={styles.content}>
        <View style={styles.heading}>
          <Text style={styles.headingTitle}>
            {activeStep?.estimated
              ? `Estimativa +${activeStep.offsetMinutes} min`
              : activeStep
                ? `Observado ${timeAgo(activeStep.image.captured_at)}`
                : 'Agora'}
          </Text>
          <Text style={styles.headingSubtitle}>
            {activeStep?.estimated
              ? 'trajetória linear das células; imagem é a última observação'
              : frameCount === 1
                ? '1 quadro real · histórico em formação'
                : `${frameCount} quadros reais · 1h até a última aquisição`}
          </Text>
        </View>
        {steps.length > 0 ? (
          <Slider
            minimumValue={0}
            maximumValue={Math.max(0, steps.length - 1)}
            step={1}
            value={index ?? currentIndex}
            onValueChange={selectIndex}
            minimumTrackTintColor={colors.accent}
            maximumTrackTintColor={colors.line}
            thumbTintColor={colors.accent}
            accessibilityLabel="Posição na linha do tempo"
          />
        ) : (
          <Text style={styles.empty}>Aguardando quadros de satélite válidos.</Text>
        )}
      </View>
      {index != null && (
        <TouchableOpacity style={styles.liveButton} onPress={goLive}>
          <Text style={styles.liveButtonText}>Ao vivo</Text>
        </TouchableOpacity>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
    backgroundColor: colors.panel,
    borderRadius: 10,
    borderColor: colors.line,
    borderWidth: 1,
    marginBottom: 10,
  },
  playButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.panel2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playIcon: { color: colors.ink, fontSize: 14 },
  content: { flex: 1 },
  heading: { marginBottom: 2 },
  headingTitle: { color: colors.ink, fontSize: 12, fontWeight: '700' },
  headingSubtitle: { color: colors.inkMute, fontSize: 11 },
  empty: { color: colors.inkMute, fontSize: 11 },
  liveButton: {
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: 6,
    backgroundColor: colors.panel2,
  },
  liveButtonText: { color: colors.accent, fontSize: 11, fontWeight: '700' },
})
