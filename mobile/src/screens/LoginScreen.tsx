import { useState } from 'react'
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { ApiError, login } from '../api'
import { colors } from '../theme'

interface Props {
  onAuthenticated: () => void
}

export function LoginScreen({ onAuthenticated }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit() {
    setLoading(true)
    setError(null)
    try {
      await login(email.trim(), password)
      onAuthenticated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao entrar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.wrap}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.card}>
        <Text style={styles.brand}>
          ⚡ Storm<Text style={styles.brandAccent}>Pulse</Text>
        </Text>
        <Text style={styles.muted}>Entre para ver seus locais e alertas.</Text>

        <Text style={styles.label}>E-mail</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="voce@exemplo.com"
          placeholderTextColor={colors.inkMute}
        />

        <Text style={styles.label}>Senha</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          placeholder="••••••••"
          placeholderTextColor={colors.inkMute}
        />

        <TouchableOpacity style={styles.btn} onPress={submit} disabled={loading}>
          {loading ? (
            <ActivityIndicator color="#04121f" />
          ) : (
            <Text style={styles.btnText}>Entrar</Text>
          )}
        </TouchableOpacity>
        {error && <Text style={styles.error}>⚠️ {error}</Text>}
      </View>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.ground, justifyContent: 'center', padding: 20 },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 16,
    padding: 24,
  },
  brand: { color: colors.ink, fontSize: 26, fontWeight: '700' },
  brandAccent: { color: colors.accent },
  muted: { color: colors.inkMute, marginTop: 4, marginBottom: 8 },
  label: { color: colors.inkDim, fontSize: 13, marginTop: 14, marginBottom: 5 },
  input: {
    backgroundColor: '#0d1626',
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.ink,
  },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    padding: 13,
    alignItems: 'center',
    marginTop: 20,
  },
  btnText: { color: '#04121f', fontWeight: '700', fontSize: 15 },
  error: { color: colors.red, marginTop: 10 },
})
