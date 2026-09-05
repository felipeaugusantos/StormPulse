import { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { ApiError, api, logout } from '../api'
import { colors } from '../theme'
import type {
  LocationItem,
  Organization,
  OrganizationMember,
  OrganizationRole,
} from '../types'

const ROLES: Exclude<OrganizationRole, 'owner'>[] = [
  'admin',
  'agronomist',
  'operator',
  'viewer',
]
const ROLE_LABEL: Record<OrganizationRole, string> = {
  owner: 'Proprietário',
  admin: 'Administrador',
  agronomist: 'Agrônomo',
  operator: 'Operador',
  viewer: 'Visualizador',
}

export function TeamScreen({ onLogout }: { onLogout: () => void }) {
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrganizationMember[]>([])
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Exclude<OrganizationRole, 'owner'>>('viewer')
  const [locationId, setLocationId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [org, memberList, locationList] = await Promise.all([
        api.organization(),
        api.organizationMembers(),
        api.locations(),
      ])
      setOrganization(org)
      setMembers(memberList)
      setLocations(locationList)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await logout()
        onLogout()
        return
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? 'Seu perfil não administra membros.'
          : 'Não foi possível carregar a equipe.',
      )
    } finally {
      setLoading(false)
    }
  }, [onLogout])

  useEffect(() => {
    load()
  }, [load])

  async function invite() {
    if (!email.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.inviteOrganizationMember({
        email: email.trim(),
        role,
        location_id: locationId,
      })
      setEmail('')
      Alert.alert('Convite enviado', 'O link é individual, expira e só pode ser usado uma vez.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível enviar o convite.')
    } finally {
      setSubmitting(false)
    }
  }

  function revoke(member: OrganizationMember) {
    Alert.alert('Revogar acesso', `Revogar imediatamente o acesso de ${member.email}?`, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Revogar',
        style: 'destructive',
        onPress: async () => {
          try {
            await api.revokeOrganizationMember(member.id)
            await load()
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Não foi possível revogar o acesso.')
          }
        },
      },
    ])
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      <Text style={styles.title}>👥 Equipe</Text>
      <Text style={styles.organization}>{organization?.name ?? 'Organização'}</Text>
      {error && <Text style={styles.error}>⚠️ {error}</Text>}
      {loading && members.length === 0 ? (
        <ActivityIndicator color={colors.accent} />
      ) : organization ? (
        <>
          <View style={styles.form}>
            <Text style={styles.sectionTitle}>Convidar membro</Text>
            <TextInput
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholder="membro@empresa.com"
              placeholderTextColor={colors.inkMute}
              style={styles.input}
            />
            <Text style={styles.label}>Função</Text>
            <View style={styles.options}>
              {ROLES.map((item) => (
                <TouchableOpacity
                  key={item}
                  style={[styles.option, role === item && styles.optionActive]}
                  onPress={() => setRole(item)}
                >
                  <Text style={[styles.optionText, role === item && styles.optionTextActive]}>
                    {ROLE_LABEL[item]}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.label}>Escopo</Text>
            <TouchableOpacity
              style={[styles.scope, locationId === null && styles.optionActive]}
              onPress={() => setLocationId(null)}
            >
              <Text style={styles.optionText}>Toda a organização</Text>
            </TouchableOpacity>
            {locations.map((location) => (
              <TouchableOpacity
                key={location.id}
                style={[styles.scope, locationId === location.id && styles.optionActive]}
                onPress={() => setLocationId(location.id)}
              >
                <Text style={styles.optionText}>{location.name}</Text>
              </TouchableOpacity>
            ))}
            <TouchableOpacity style={styles.button} onPress={invite} disabled={submitting}>
              <Text style={styles.buttonText}>{submitting ? 'Enviando…' : 'Enviar convite'}</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.sectionTitle}>Membros</Text>
          {members.map((member) => (
            <View key={member.id} style={styles.card}>
              <Text style={styles.memberName}>{member.full_name || member.email}</Text>
              <Text style={styles.meta}>{member.email}</Text>
              <Text style={styles.meta}>
                {ROLE_LABEL[member.role]} ·{' '}
                {member.organization_wide_access ? 'organização' : 'acesso restrito'}
              </Text>
              {member.access_expires_at && (
                <Text style={styles.meta}>
                  Expira em {new Date(member.access_expires_at).toLocaleString('pt-BR')}
                </Text>
              )}
              {member.role !== 'owner' && member.is_active && (
                <TouchableOpacity onPress={() => revoke(member)}>
                  <Text style={styles.revoke}>Revogar acesso</Text>
                </TouchableOpacity>
              )}
            </View>
          ))}
        </>
      ) : null}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { padding: 16, paddingTop: 56, paddingBottom: 32 },
  title: { color: colors.ink, fontSize: 22, fontWeight: '700' },
  organization: { color: colors.inkDim, marginBottom: 16 },
  error: { color: colors.red, marginBottom: 12 },
  sectionTitle: { color: colors.ink, fontSize: 16, fontWeight: '700', marginBottom: 10 },
  form: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 18,
  },
  input: {
    backgroundColor: colors.panel2,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    color: colors.ink,
    marginBottom: 10,
  },
  label: { color: colors.inkMute, fontSize: 12, marginBottom: 6 },
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginBottom: 12 },
  option: { borderColor: colors.line, borderWidth: 1, borderRadius: 8, padding: 8 },
  optionActive: { borderColor: colors.accent, backgroundColor: colors.panel2 },
  optionText: { color: colors.inkDim, fontSize: 12 },
  optionTextActive: { color: colors.accent },
  scope: { borderColor: colors.line, borderWidth: 1, borderRadius: 8, padding: 9, marginBottom: 6 },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 11, alignItems: 'center', marginTop: 8 },
  buttonText: { color: '#04121f', fontWeight: '700' },
  card: { backgroundColor: colors.panel, borderColor: colors.line, borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 10 },
  memberName: { color: colors.ink, fontWeight: '700' },
  meta: { color: colors.inkMute, fontSize: 12, marginTop: 3 },
  revoke: { color: colors.red, fontSize: 13, marginTop: 10 },
})
