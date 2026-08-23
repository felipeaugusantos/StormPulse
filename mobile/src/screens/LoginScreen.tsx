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
import { ApiError, login, register } from '../api'
import { colors } from '../theme'

interface Props {
  onAuthenticated: () => void
}

const MIN_PASSWORD_LENGTH = 8

export function LoginScreen({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const isRegister = mode === 'register'

  function switchMode(next: 'login' | 'register') {
    setMode(next)
    setError(null)
    setPassword('')
    setConfirmPassword('')
  }

  async function submit() {
    setError(null)

    if (isRegister && password !== confirmPassword) {
      setError('As senhas não coincidem')
      return
    }
    if (isRegister && password.length < MIN_PASSWORD_LENGTH) {
      setError(`A senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres`)
      return
    }

    setLoading(true)
    try {
      if (isRegister) {
        await register(email.trim(), password, fullName.trim() || undefined)
      } else {
        await login(email.trim(), password)
      }
      onAuthenticated()
    } catch (err) {
      const fallback = isRegister ? 'Falha ao criar conta' : 'Falha ao entrar'
      setError(err instanceof ApiError ? err.message : fallback)
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
        <Text style={styles.muted}>
          {isRegister ? 'Criar conta — leva menos de um minuto.' : 'Entre para ver seus locais e alertas.'}
        </Text>

        {isRegister && (
          <>
            <Text style={styles.label}>Nome (opcional)</Text>
            <TextInput
              style={styles.input}
              value={fullName}
              onChangeText={setFullName}
              autoCapitalize="words"
              placeholder="Seu nome"
              placeholderTextColor={colors.inkMute}
            />
          </>
        )}

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

        {isRegister && (
          <>
            <Text style={styles.label}>Confirmar senha</Text>
            <TextInput
              style={styles.input}
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              secureTextEntry
              placeholder="••••••••"
              placeholderTextColor={colors.inkMute}
            />
          </>
        )}

        <TouchableOpacity style={styles.btn} onPress={submit} disabled={loading}>
          {loading ? (
            <ActivityIndicator color="#04121f" />
          ) : (
            <Text style={styles.btnText}>{isRegister ? 'Criar conta' : 'Entrar'}</Text>
          )}
        </TouchableOpacity>
        {error && <Text style={styles.error}>⚠️ {error}</Text>}

        <TouchableOpacity
          style={styles.switchModeBtn}
          onPress={() => switchMode(isRegister ? 'login' : 'register')}
        >
          <Text style={styles.muted}>
            {isRegister ? 'Já tem conta? ' : 'Não tem conta? '}
            <Text style={styles.link}>{isRegister ? 'Entrar' : 'Criar conta'}</Text>
          </Text>
        </TouchableOpacity>
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
  switchModeBtn: { marginTop: 16, alignItems: 'center' },
  link: { color: colors.accent, fontWeight: '700' },
})
