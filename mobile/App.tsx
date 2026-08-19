import { useEffect, useState } from 'react'
import { ActivityIndicator, View } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { loadToken } from './src/api'
import { colors } from './src/theme'
import { LoginScreen } from './src/screens/LoginScreen'
import { HomeScreen } from './src/screens/HomeScreen'

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
        <HomeScreen onLogout={() => setAuthed(false)} />
      ) : (
        <LoginScreen onAuthenticated={() => setAuthed(true)} />
      )}
    </SafeAreaProvider>
  )
}
