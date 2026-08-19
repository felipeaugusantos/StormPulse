# ⚡ StormPulse

**StormPulse** é um painel de monitoramento de clima e tempestades em tempo real.
Além da previsão do tempo tradicional, ele calcula um **Índice de Pulso** (0–100) que
resume, em um único número, o risco de tempo severo nas próximas 24 horas — combinando
rajadas de vento, atividade de tempestades e volume de chuva.

Construído com **React + TypeScript + Vite** e alimentado pela API gratuita
[Open-Meteo](https://open-meteo.com) — **sem necessidade de chave de API**.

## ✨ Funcionalidades

- 🔎 **Busca de cidades** com geocodificação (e botão "usar minha localização")
- 🌡️ **Condições atuais**: temperatura, sensação, umidade, vento, rajadas, pressão e nuvens
- 🚨 **Índice StormPulse**: avaliação de risco (calmo → atento → alerta → severo) com
  alertas legíveis
- ⏱️ **Previsão horária** para as próximas 24 horas
- 📅 **Previsão de 7 dias** com faixa de temperatura e probabilidade de chuva
- 🎨 **Fundo dinâmico** que muda conforme o tempo (limpo, nublado, chuva, tempestade…)
- 🔁 **Atualização automática** a cada 5 minutos
- 📱 **Responsivo** e otimizado para telas pequenas

## 🚀 Rodando localmente

```bash
npm install
npm run dev        # inicia o servidor de desenvolvimento
npm run build      # gera o build de produção em dist/
npm run preview    # pré-visualiza o build
```

Abra o endereço exibido no terminal (por padrão `http://localhost:5173`).

## 🏗️ Estrutura

```
src/
├── api/openMeteo.ts        # Cliente das APIs de geocodificação e previsão
├── hooks/useWeather.ts     # Carregamento + auto-refresh dos dados
├── lib/
│   ├── weatherCodes.ts     # Códigos WMO → rótulo/ícone/tema
│   ├── storm.ts            # Cálculo do Índice StormPulse
│   └── format.ts           # Helpers de formatação
└── components/
    ├── SearchBar.tsx
    ├── StormAlert.tsx
    ├── CurrentConditions.tsx
    ├── HourlyForecast.tsx
    └── DailyForecast.tsx
```

## ☁️ Deploy

O repositório inclui um workflow (`.github/workflows/deploy.yml`) que publica
automaticamente no **GitHub Pages** a cada push na branch `main`. Basta habilitar
o GitHub Pages (fonte: *GitHub Actions*) nas configurações do repositório.

## 📄 Dados

Fornecidos por [Open-Meteo](https://open-meteo.com/) sob a licença
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
