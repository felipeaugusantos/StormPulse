import { useEffect, useState } from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { ActivityIndicator } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { loadToken } from './src/api'
import { colors } from './src/theme'
import { LoginScreen } from './src/screens/LoginScreen'
import { HomeScreen } from './src/screens/HomeScreen'
import { AgroScreen } from './src/screens/AgroScreen'
import { LocationsScreen } from './src/screens/LocationsScreen'

type Tab = 'storm' | 'agro' | 'locations'

function MainTabs({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>('storm')

  return (
    <View style={{ flex: 1 }}>
      {tab === 'storm' && <HomeScreen onLogout={onLogout} />}
      {tab === 'agro' && <AgroScreen onLogout={onLogout} />}
      {tab === 'locations' && <LocationsScreen onLogout={onLogout} />}

      <SafeAreaView edges={['bottom']} style={styles.tabBar}>
        <TabButton label="⛈️ Tempestade" active={tab === 'storm'} onPress={() => setTab('storm')} />
        <TabButton label="🌾 Agro" active={tab === 'agro'} onPress={() => setTab('agro')} />
        <TabButton
          label="📍 Locais"
          active={tab === 'locations'}
          onPress={() => setTab('locations')}
        />
      </SafeAreaView>
    </View>
  )
}

function TabButton({
  label,
  active,
  onPress,
}: {
  label: string
  active: boolean
  onPress: () => void
}) {
  return (
    <TouchableOpacity style={styles.tabButton} onPress={onPress}>
      <Text style={[styles.tabButtonText, active && styles.tabButtonTextActive]}>{label}</Text>
    </TouchableOpacity>
  )
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    loadToken().then((token) => setAuthed(token !== null))
  }, [])

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      {authed === null ? (
        <View style={{ flex: 1, backgroundColor: colors.ground, justifyContent: 'center' }}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : authed ? (
        <MainTabs onLogout={() => setAuthed(false)} />
      ) : (
        <LoginScreen onAuthenticated={() => setAuthed(true)} />
      )}
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  tabBar: {
    flexDirection: 'row',
    borderTopColor: colors.line,
    borderTopWidth: 1,
    backgroundColor: colors.panel,
  },
  tabButton: { flex: 1, paddingVertical: 12, alignItems: 'center' },
  tabButtonText: { color: colors.inkMute, fontSize: 12 },
  tabButtonTextActive: { color: colors.accent, fontWeight: '700' },
})
