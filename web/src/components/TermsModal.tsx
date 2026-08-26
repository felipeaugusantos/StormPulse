interface Props {
  onClose: () => void
}

/** Termos de Uso e Política de Privacidade (FASE 8, ADR-0059).
 *
 * MINUTA — cobre o essencial (dados coletados, uso de terceiros, direitos
 * do titular sob a LGPD) mas não foi revisada por um advogado. Marcado
 * como pendência manual no relatório final desta rodada; não publique em
 * produção real sem essa revisão. */
export function TermsModal({ onClose }: Props) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Termos de Uso e Política de Privacidade</h2>
          <button type="button" className="link-btn" onClick={onClose} aria-label="Fechar">
            ✕
          </button>
        </div>
        <div className="terms-body">
          <p className="muted">
            <strong>Minuta.</strong> Este texto ainda não passou por revisão jurídica — serve
            para deixar claro o que o StormPulse faz com seus dados até que uma versão revisada
            substitua esta.
          </p>

          <h3>O que coletamos</h3>
          <p>
            E-mail, senha (armazenada com hash, nunca em texto puro), nome (opcional) e as
            localizações que você cadastrar (nome, coordenadas, cultura, se aplicável). E-mail e
            nome são criptografados em repouso no banco de dados.
          </p>

          <h3>Como usamos</h3>
          <p>
            Só para operar o serviço: gerar alertas de tempestade/agro para as localizações que
            você cadastrar, autenticar seu acesso, e enviar e-mails transacionais (confirmação de
            conta, redefinição de senha). Nunca vendemos ou compartilhamos seus dados com
            terceiros para fins de publicidade.
          </p>

          <h3>Terceiros envolvidos</h3>
          <p>
            Dados meteorológicos vêm de fontes públicas (INMET, CPTEC/INPE, satélite GOES,
            REDEMET). E-mails transacionais são entregues via AWS SES. Login opcional via Google
            usa o OAuth do Google — verificamos o token no servidor, nunca armazenamos sua senha
            do Google.
          </p>

          <h3>Seus direitos (LGPD)</h3>
          <p>
            Você pode excluir sua conta e todos os dados associados a qualquer momento, pelo
            próprio painel (Configurações → Excluir minha conta). Para dúvidas sobre seus dados,
            entre em contato pelo e-mail de suporte informado no rodapé do site.
          </p>

          <h3>Retenção</h3>
          <p>
            Seus dados ficam armazenados enquanto sua conta existir. Ao excluir a conta, os
            dados são apagados do banco — não mantemos cópia depois disso, exceto o que a lei
            exigir por período determinado (ex.: logs de segurança).
          </p>
        </div>
      </div>
    </div>
  )
}
