# FAQ de Recarga Comercial · ChargeGrid Intelligence

**Documento do projeto** · Grupo 2 · Turma 1CCR · FIAP × GoodWe EV Challenge 2026 · Outubro de 2026

Perguntas frequentes recebidas de operadores comerciais (shoppings, supermercados e estacionamentos) durante o piloto.

## Operação e potência

**Os carregadores podem derrubar a energia da loja?**
Não, desde que o controle de demanda esteja ativo. A plataforma lê o medidor geral a cada 15 segundos e reduz a potência dos carregadores a partir de 85% da demanda contratada. A partir de 100%, novas sessões ficam suspensas. Detalhes no Manual de Operação, seção 3.

**Quantos carros consigo carregar ao mesmo tempo?**
Depende da folga (headroom) do momento, e não do número de conectores. A plataforma distribui a folga entre as sessões ativas. Se a folga for pequena, todos os carros carregam, porém mais devagar.

**O que acontece se acabar a energia no meio da recarga?**
A transação é encerrada com a última leitura válida e o cliente paga apenas a energia efetivamente entregue. Quando a energia volta, o conector retorna a Available.

**O carregador entrou em falha. O sistema conserta?**
Não. A plataforma retira o conector da operação, encerra a sessão e abre chamado. Manutenção e diagnóstico físico são feitos por técnico credenciado do fabricante.

## Cobrança

**Posso cobrar mais caro no horário de pico?**
Sim. A política tarifária do piloto aplica multiplicador de 1,30 entre 18h e 21h nos dias úteis. A base regulatória que permite preço livre na recarga deve ser consultada nos documentos da ANEEL presentes na base.

**Como provo que o cliente pagou exatamente o que consumiu?**
Pelo comprovante da sessão, que registra ID de transação OCPP, leituras inicial e final e a tarifa aplicada, e pela conferência com o medidor MODBUS. Divergência acima de 1% marca a sessão para revisão.

**O cliente pode contestar a cobrança?**
Sim. O operador abre o registro da sessão pelo ID da transação. Se houver divergência acima de 1% entre OCPP e MODBUS, prevalece o menor valor.

## Equipamentos e expansão

**Posso comprar carregadores de outras marcas depois?**
A plataforma integra qualquer carregador que implemente OCPP 1.6J com perfis de Smart Charging. A conformidade deve ser confirmada no datasheet do fabricante ou na certificação da Open Charge Alliance. Não há lista de compatibilidade garantida além do que está documentado na base.

**Qual a potência máxima do carregador GoodWe?**
Consulte o datasheet oficial do modelo instalado, presente na base de conhecimento. A plataforma usa o máximo informado pelo próprio carregador e nunca presume um valor.

## Limites do assistente

**O assistente pode me dizer se vale a pena financiar mais carregadores?**
Não. O assistente mostra números da operação (receita, energia, ocupação), mas decisão de investimento e financiamento deve ser tomada com contador ou consultor financeiro habilitado.

**O assistente pode me orientar a trocar o disjuntor?**
Não. Intervenção em instalação elétrica é feita somente por eletricista ou engenheiro eletricista habilitado.
