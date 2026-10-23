# Manual de Operação do ChargeGrid Intelligence

**Documento do projeto** · Grupo 2 · Turma 1CCR · FIAP × GoodWe EV Challenge 2026 · Versão 4.0 · Outubro de 2026

Este manual descreve o comportamento operacional da plataforma ChargeGrid Intelligence no Contexto A (recarga comercial). Ele define as regras que a plataforma aplica, não as especificações elétricas dos equipamentos. Especificações de hardware (potência nominal, corrente, grau de proteção, temperatura de operação) devem ser consultadas exclusivamente nos datasheets oficiais do fabricante.

## 1. Visão geral da plataforma

O ChargeGrid Intelligence é a camada lógica que transforma um conjunto de eletropostos em uma operação comercial integrada. A plataforma orquestra a potência disponível no ponto de entrega do estabelecimento, registra o ciclo completo de cada sessão de recarga, aplica a política tarifária vigente e comunica eventos ao operador.

O piloto de referência é o EV Charger GoodWe instalado na FIAP, integrado ao ecossistema digital da GoodWe. A plataforma não substitui o firmware do carregador: ela envia comandos e lê eventos pelos protocolos abertos que o carregador expõe.

## 2. Arquitetura de integração

A integração tem duas vias independentes, e a independência é proposital.

**Via de controle e registro (OCPP 1.6J).** Para carregadores que implementam OCPP, o carregador atua como Charge Point e o ChargeGrid como sistema central de gestão (CSMS). A comunicação usa WebSocket com mensagens JSON. Por esta via a plataforma recebe StatusNotification, StartTransaction, MeterValues e StopTransaction, e envia SetChargingProfile, RemoteStartTransaction e RemoteStopTransaction.

**Via de medição e controle local (MODBUS).** Um medidor de energia instalado no quadro de alimentação dos carregadores é lido via MODBUS TCP (ou MODBUS RTU sobre RS-485 com gateway). A mesma via lê o medidor geral do estabelecimento, que informa o consumo da loja.

**Caso do carregador GoodWe da série HCA G2.** O datasheet do fabricante declara Modbus TCP como protocolo de comunicação, além de Wi-Fi, LAN, Bluetooth e RS485, e não declara OCPP. Para esse equipamento a plataforma usa a via MODBUS e a função de controle dinâmico de carga do próprio carregador. A via OCPP se aplica aos carregadores de outros fabricantes que a implementam. A plataforma não presume suporte a OCPP em nenhum modelo: o suporte deve constar no datasheet ou na certificação do fabricante.

Quando as duas vias estão disponíveis, elas medem a mesma energia por caminhos diferentes, e a plataforma compara os valores ao final de cada sessão (ver seção 6.3).

## 3. Controle de demanda

### 3.1 Conceitos

- **Demanda contratada:** potência ativa, em kW, contratada pelo estabelecimento junto à distribuidora, conforme o contrato de fornecimento.
- **Consumo da loja:** potência ativa instantânea medida no medidor geral, descontada a parcela dos carregadores.
- **Headroom (folga):** potência disponível para recarga, calculada como demanda contratada menos consumo da loja.

### 3.2 Limiares de operação

A plataforma trabalha com três limiares calculados sobre a demanda contratada:

| Limiar | Valor | Comportamento |
|---|---|---|
| Atenção | 85% da demanda contratada | Inicia redução escalonada da potência dos carregadores |
| Crítico | 95% da demanda contratada | Reduz todos os conectores à corrente mínima de carga |
| Limite de segurança | 100% da demanda contratada | Suspende novas sessões (SuspendedEVSE) até o consumo voltar abaixo de 85% |

O ciclo de leitura do medidor geral é de 15 segundos. O comando SetChargingProfile é reenviado sempre que o headroom calculado varia mais de 2 kW em relação ao último perfil aplicado.

### 3.3 Distribuição do headroom entre sessões

1. A plataforma lê o consumo da loja e calcula o headroom.
2. Reserva-se uma margem de proteção de 5% da demanda contratada, que não é distribuída.
3. O headroom restante é dividido igualmente entre as sessões ativas, respeitando o máximo de cada conector informado pelo próprio carregador.
4. Sessões com prioridade (frota cadastrada ou cliente com reserva) recebem até 1,5 vez a fatia das demais.

**Exemplo de cálculo.** Estabelecimento com 200 kW contratados e consumo da loja de 170 kW. O headroom bruto é de 30 kW. Descontada a margem de proteção de 10 kW (5% de 200 kW), restam 20 kW distribuíveis. Com quatro sessões ativas, cada uma recebe 5 kW.

### 3.4 Penalidade evitada

Ultrapassar a demanda contratada gera cobrança de ultrapassagem pela distribuidora, nas condições definidas pela regulação da ANEEL e pelo contrato de fornecimento. O controle de demanda existe para que a recarga nunca seja a causa da ultrapassagem. O cálculo da cobrança deve ser conferido na fatura e na regulação vigente, não neste manual.

## 4. Ciclo da sessão de recarga

| Etapa | Evento OCPP | Registro na plataforma |
|---|---|---|
| Conexão do veículo | StatusNotification (Preparing) | Conector reservado à sessão |
| Autorização | Authorize | Identificação por app, RFID ou QR Code com Pix |
| Início | StartTransaction | ID de transação, timestamp UTC e leitura inicial do medidor em Wh |
| Durante a recarga | MeterValues a cada 60 segundos | Energia acumulada, potência instantânea e estado de carga quando o veículo informa |
| Fim | StopTransaction | Leitura final, motivo do encerramento e energia total |
| Desconexão | StatusNotification (Finishing, depois Available) | Início da contagem de ociosidade encerrada |

Motivos de encerramento registrados: solicitação do motorista (Local), comando remoto do operador (Remote), veículo carregado (EVDisconnected), falha (PowerLoss ou Other). Em caso de queda de energia ou falha do conector, a transação é encerrada com o último MeterValues válido e o cliente paga apenas a energia efetivamente entregue.

## 5. Relatórios e indicadores

| Indicador | Definição | Meta do piloto |
|---|---|---|
| Disponibilidade | Tempo em Available ou Charging dividido pelo tempo total do período | 97% ao mês |
| Taxa de sessões concluídas | Sessões encerradas sem falha divididas pelo total de sessões | 98% |
| Energia por sessão | Média de kWh entregues por sessão | acompanhamento |
| Receita por conector | Receita líquida do período dividida pelo número de conectores | acompanhamento |
| Divergência de medição | Diferença percentual entre energia OCPP e energia MODBUS | até 1% |
| Tempo ocioso médio | Minutos com veículo conectado sem receber energia | até 10 minutos |

Os relatórios são consolidados diariamente às 00h05 e enviados ao operador por e-mail e painel web.

## 6. Faturamento

### 6.1 Fórmula da sessão

Valor da sessão = (energia entregue em kWh × tarifa do conector na faixa horária) + taxa de ociosidade, quando houver.

A energia entregue é a diferença entre a leitura final e a leitura inicial do StopTransaction e do StartTransaction, convertida de Wh para kWh com três casas decimais. O valor final é arredondado para duas casas decimais.

### 6.2 Tarifas

As tarifas vigentes por tipo de conector e faixa horária estão na Política Tarifária ChargeGrid (documento próprio da base). O manual de operação não fixa preços.

### 6.3 Auditoria e contestação

Cada sessão gera um comprovante com ID de transação, timestamps de início e fim, leituras inicial e final, energia, tarifa aplicada e valor. Quando a divergência entre a energia do OCPP e a do MODBUS ultrapassa 1%, a sessão é marcada para revisão e a cobrança usa o menor dos dois valores, em favor do cliente. Registros de sessão são retidos por cinco anos.

## 7. Alarmes e encaminhamentos

| Alarme | Origem | Ação da plataforma | Encaminhamento |
|---|---|---|---|
| Conector em Faulted | StatusNotification | Retira o conector da distribuição de potência e encerra a transação | Técnico credenciado do fabricante |
| Perda de comunicação OCPP acima de 5 minutos | Heartbeat ausente | Marca o carregador como Unavailable no painel | Equipe de TI do estabelecimento |
| Divergência de medição acima de 1% | Comparação OCPP × MODBUS | Marca sessão para revisão | Operador comercial |
| Consumo acima de 95% da demanda | Medidor geral | Redução à corrente mínima | Operador comercial; se recorrente, engenheiro eletricista para revisão da demanda contratada |

A plataforma nunca orienta intervenção física em quadro, cabeamento ou equipamento energizado. Toda intervenção é executada por profissional habilitado, com responsabilidade técnica registrada.
