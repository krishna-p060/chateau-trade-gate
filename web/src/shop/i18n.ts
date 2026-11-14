// Tiny i18n for the webshop: a dictionary, the current language (module-level, set by ShopApp before
// it re-renders) and locale-aware formatters. Server-written texts arrive already translated.

export type Lang = 'en' | 'fi'

export function initialLang(): Lang {
  const s = localStorage.getItem('aimo.lang')
  if (s === 'en' || s === 'fi') return s
  return (navigator.language || '').toLowerCase().startsWith('fi') ? 'fi' : 'en'
}

let current: Lang = initialLang()
document.documentElement.lang = current

export const getLang = () => current
export function setLang(l: Lang) {
  current = l
  localStorage.setItem('aimo.lang', l)
  document.documentElement.lang = l
}

const en = {
  // header
  brand: 'Valio Aimo', app: 'Aimo Assistant', prototype: 'prototype',
  tab_assistant: 'Assistant', tab_approvals: 'Approvals', tab_valio: 'Valio view', tab_prefs: 'Preferences',
  dev_console: 'Developer console', loading: 'Loading…', signed_in_as: 'Signed in as', language: 'Language',
  // toasts
  err_generic: 'Something went wrong', err_customers: 'Could not load customers', err_start: 'Could not start the assistant',
  err_send: 'Could not send', err_template_check: 'Could not check the order template', err_option: 'Could not change the option',
  err_remove: 'Could not remove the line', err_order: 'Order not placed', err_new: 'Could not start a new conversation',
  err_answer: 'Could not send your answer', err_approve_list: 'Could not approve the list', err_reference: 'Could not save your reference',
  err_notify: 'Could not set the notification', err_template_save: 'Could not save the order template', err_decision: 'Decision failed',
  err_save: 'Could not save', err_lang: 'Could not switch the conversation language',
  toast_approved: 'Order approved', toast_rejected: 'Order rejected',
  toast_approved_body: '{id} is confirmed and signed by Valio.', toast_rejected_body: '{id} will not be delivered.',
  toast_prefs_saved: 'Saved — your purchasing mandate was re-signed ✓',
  // chat
  new_chat: 'New', ph_request: 'Tell Aimo what you need…', ph_answer: 'Or type your answer…',
  ph_list: 'Ask for a change to the list…', ph_cart: 'Ask for a change to the cart…', listening: 'Listening…',
  aimo_asked: 'Aimo asked:', answer_right: '— answer on the right →', steps_one: '{n} step', steps_other: '{n} steps',
  stop_listening: 'Stop listening', speak: 'Speak', send: 'Send',
  // stepper
  step_request: 'Request', step_ingredients: 'Ingredients', step_products: 'Products', step_order: 'Order',
  your_list: 'Your list', you_approve: 'You approve every step',
  // start
  start_title: 'What are you cooking?', start_sub: 'You approve every step. Nothing is ordered until you confirm.',
  your_templates: 'Your order templates', check_next: 'Check for next delivery', items_n: '{n} items',
  start_hint: 'or type or speak your own request on the left',
  // questions
  quick_question: 'Quick question', quick_questions: 'Quick questions', type_answer_left: 'or type your answer on the left',
  continue: 'Continue',
  // working
  updating_list: 'Updating the list…', working: 'Working on it…', checking_live: 'Checking live price and stock…',
  f_products: 'products', f_checked: 'checked live', f_candidates: 'candidates',
  stalled_error: 'Something went wrong while finding products. Your approved list is safe.',
  stalled_reply: 'Aimo replied in the chat — nothing was ordered.', try_again: 'Try again', try_again_msg: 'Please try again.',
  // ingredients
  other: 'Other', portions_n: '{n} portions', from_recipe: 'From your saved recipe', scaled: 'scaled {a} → {b} portions',
  estimate: 'Aimo’s estimate — no saved recipe yet', saved_recipe: 'Saved as your recipe', save_recipe: 'Save as my recipe',
  check_ingredients: 'Check the ingredients', delivery_lc: 'delivery', ingredient_ph: 'Ingredient', less: 'Less', more: 'More',
  remove: 'Remove', edited: 'Edited by you', add_ingredient: 'Add ingredient', nothing_ordered: 'Nothing is ordered yet.',
  edits_one: '{n} edit by you', edits_other: '{n} edits by you', looks_right: 'Looks right — find products',
  // cart
  your_cart: 'Your cart', delivery: 'Delivery', notes_n: 'Notes ({n})', hide_notes: 'Hide notes', add_reference: 'Add reference',
  reference_ph: 'Your reference, e.g. Saturday party', approved_by_you: 'Ingredients approved by you',
  changes_one: '{n} change', changes_other: '{n} changes',
  not_available: 'Not available', late: 'Late · {d}', in_stock: 'In stock', orderable: 'Orderable', no_product: 'No product found',
  choose_one: 'Choose one', replaces: 'Replaces', your_usual: 'Your usual', options_n: '{n} options', details: 'Details',
  same_price: 'same price', delivery_d: 'Delivery {d}', estimate_paren: '(estimate)', order_by: 'Order by {d}',
  co2: '{n} kg CO₂', in_stock_n: 'In stock ({n})', contains: 'Contains {list}', notify_ok: 'We’ll notify you ✓',
  notify_me: 'Notify me when {name} is back', excl_vat: 'excl. VAT', incl_vat: '{x} incl. VAT', per_portion: '{x} / portion',
  choose_first_one: 'Choose {n} option first', choose_first_other: 'Choose {n} options first', cutoff_passed: 'Cut-off passed',
  confirm_before: 'Confirm before {d}', in_dur: 'in {d}', send_approval: 'Send for approval', confirm_order: 'Confirm order',
  // order
  order_confirmed: 'Order confirmed', waiting_for: 'Waiting for {who}', your_approver: 'your approver', order_rejected: 'Order not accepted',
  ref_r: 'Ref. {r}', signed_valio: 'Signed by Valio', new_order: 'New order', products_n: '{n} products',
  saved_template: 'Saved as order template', save_template: 'Save as order template', save: 'Save',
  // approvals
  appr_title: 'Approvals', appr_sub: 'Orders above a customer’s own limit wait here for the person their purchasing mandate names. Nothing is sent to the warehouse until they decide.',
  needs_approval: 'Needs your approval', via_aimo: 'via Aimo Assistant', ordered_by: 'Ordered by {name}', order: 'Order',
  lines_one: '{n} line', lines_other: '{n} lines', why_needs: 'Why it needs you', above_limit: 'Above the customer’s approval limit.',
  note_ph: 'Add a note for the kitchen (optional)', reject: 'Reject', approve: 'Approve',
  audit_note: 'Your decision is recorded in the tamper-evident audit trail; on approval Valio signs the order confirmation.',
  appr_empty: 'Nothing waiting for approval', appr_empty_body: 'When an order is above the customer’s limit or needs a second look, it shows up here with plain-language reasons.',
  // valio view
  vv_kicker: 'Valio Aimo internal', vv_title: 'What the assistant tells Valio',
  vv_sub: 'Every substitution and preference the customer makes in the cart becomes a signal for Valio’s purchasing and assortment — so do back-in-stock requests and demand the assortment couldn’t meet.',
  kpi_orders: 'Orders', kpi_via: '{n} via Aimo Assistant', kpi_value: 'Confirmed value', kpi_confirmed: '{n} confirmed · excl. VAT',
  kpi_subs: 'Substitutions accepted', kpi_subs_sub: '{a} back-in-stock · {b} unmet', kpi_audit: 'Audit trail',
  chain_ok: 'Chain intact', chain_broken: 'Chain broken', chain_n: '{n} hash-linked entries verified',
  signals: 'Signals for Valio Aimo', recent_orders: 'Recent orders',
  signals_empty: 'No signals yet. Confirm a cart where the customer accepts a substitute or picks a different option, and it appears here.',
  th_customer: 'Customer', th_channel: 'Channel', th_status: 'Status', th_total: 'Total', ch_shop: 'Webshop · Aimo', ch_api: 'API agent',
  no_orders: 'No orders yet', sig_sub: 'Substitution accepted', sig_pref: 'Preference', sig_notify: 'Back-in-stock request',
  sig_unmet: 'Demand we couldn’t meet', sig_notify_body: 'Customer wants to know when it is available again.',
  sig_unmet_body: 'nothing suitable in the assortment.', needed_by: 'needed by {d}',
  st_confirmed: 'Confirmed', st_pending: 'Pending approval', st_rejected: 'Rejected',
  tab_break: 'Try to break it', bi_title: 'Try to break the gate',
  bi_sub: 'Each button makes a rogue agent send the gate something the customer never signed. No model and no API key are involved: you see what the gate answered and the audit rows it wrote.',
  bi_scratch: 'Attempts run on a scratch copy of the gate: same code, catalog and Valio connection, a separate order book. No customer order changes.',
  bi_run: 'Run', bi_again: 'Run again', bi_run_all: 'Run all', bi_running: 'Running…', bi_ms: '{n} ms',
  bi_steps: 'What the agent sent', bi_answer: 'What the gate answered', bi_audit: 'Audit rows the gate wrote', bi_no_audit: 'No audit rows were written.',
  bi_stopped: 'Stopped', bi_not_stopped: 'Not stopped', bi_v_refused: 'Refused', bi_v_blocked: 'Blocked', bi_v_held: 'Held for approval', bi_v_detected: 'Detected',
  bi_tally: '{a} of {n} attempts stopped', bi_load_err: 'Could not load the attempts', bi_run_err: 'The attempt did not run', bi_empty: 'This server has no attempts to run.',
  nokey_title: 'The assistant needs ANTHROPIC_API_KEY in .env.', nokey_body: 'The gate itself runs without it.',
  err_session_lost: 'The server restarted', err_session_lost_body: 'A new conversation is open. Orders already placed are kept; send your request again.',
  // preferences
  prefs_title: 'Preferences', prefs_for: 'How Aimo Assistant buys for {name}.',
  prefs_explainer: 'Aimo Assistant follows these preferences. They are signed into your purchasing mandate, which Valio checks on every order.',
  prio_title: 'What matters to you', prio_hint: 'In priority order. The assistant uses these to rank options.', add_priority: 'Add a priority',
  allergens_title: 'Allergens to avoid', allergens_hint: 'Products containing these are never put in your cart. Products without allergen data are flagged.',
  none: 'None', allergen_ph: 'e.g. sesame', remove_x: 'Remove {x}', limit_title: 'Approval limit', limit_hint: 'Orders above this go to {who}.',
  per_order: 'per order, excl. VAT', templates_title: 'Order templates',
  auto_confirm: 'Confirm my order templates automatically when everything is available', save_prefs: 'Save preferences',
  recipes_title: 'Your recipes', recipes_hint: 'Aimo scales these to the number of portions you ask for. Save new ones from the ingredient list.',
  no_recipes: 'No saved recipes yet.',
  // relative time
  just_now: 'just now', min_ago: '{n} min ago', h_ago: '{n} h ago', days: '{n} days',
}

export type Key = keyof typeof en

const fi: Record<Key, string> = {
  brand: 'Valio Aimo', app: 'Aimo-avustaja', prototype: 'prototyyppi',
  tab_assistant: 'Avustaja', tab_approvals: 'Hyväksynnät', tab_valio: 'Valion näkymä', tab_prefs: 'Asetukset',
  dev_console: 'Kehittäjäkonsoli', loading: 'Ladataan…', signed_in_as: 'Kirjautuneena', language: 'Kieli',
  err_generic: 'Jokin meni vikaan', err_customers: 'Asiakkaita ei voitu ladata', err_start: 'Avustajaa ei voitu käynnistää',
  err_send: 'Viestiä ei voitu lähettää', err_template_check: 'Tilauspohjaa ei voitu tarkistaa', err_option: 'Vaihtoehtoa ei voitu vaihtaa',
  err_remove: 'Riviä ei voitu poistaa', err_order: 'Tilausta ei tehty', err_new: 'Uutta keskustelua ei voitu aloittaa',
  err_answer: 'Vastausta ei voitu lähettää', err_approve_list: 'Listaa ei voitu hyväksyä', err_reference: 'Viitettä ei voitu tallentaa',
  err_notify: 'Ilmoitusta ei voitu asettaa', err_template_save: 'Tilauspohjaa ei voitu tallentaa', err_decision: 'Päätös epäonnistui',
  err_save: 'Tallennus epäonnistui', err_lang: 'Keskustelun kieltä ei voitu vaihtaa',
  toast_approved: 'Tilaus hyväksytty', toast_rejected: 'Tilaus hylätty',
  toast_approved_body: '{id} on vahvistettu ja Valion allekirjoittama.', toast_rejected_body: '{id} ei toimiteta.',
  toast_prefs_saved: 'Tallennettu – ostovaltuutuksesi allekirjoitettiin uudelleen ✓',
  new_chat: 'Uusi', ph_request: 'Kerro Aimolle mitä tarvitset…', ph_answer: 'Tai kirjoita vastauksesi…',
  ph_list: 'Pyydä muutosta listaan…', ph_cart: 'Pyydä muutosta ostoskoriin…', listening: 'Kuunnellaan…',
  aimo_asked: 'Aimo kysyi:', answer_right: '– vastaa oikealla →', steps_one: '{n} vaihe', steps_other: '{n} vaihetta',
  stop_listening: 'Lopeta kuuntelu', speak: 'Puhu', send: 'Lähetä',
  step_request: 'Pyyntö', step_ingredients: 'Raaka-aineet', step_products: 'Tuotteet', step_order: 'Tilaus',
  your_list: 'Oma lista', you_approve: 'Hyväksyt jokaisen vaiheen',
  start_title: 'Mitä olet valmistamassa?', start_sub: 'Hyväksyt jokaisen vaiheen. Mitään ei tilata ennen vahvistustasi.',
  your_templates: 'Tilauspohjasi', check_next: 'Tarkista seuraavaan toimitukseen', items_n: '{n} tuotetta',
  start_hint: 'tai kirjoita tai sano oma pyyntösi vasemmalla',
  quick_question: 'Nopea kysymys', quick_questions: 'Nopeat kysymykset', type_answer_left: 'tai kirjoita vastauksesi vasemmalla',
  continue: 'Jatka',
  updating_list: 'Päivitetään listaa…', working: 'Työn alla…', checking_live: 'Tarkistetaan hinta ja saatavuus…',
  f_products: 'tuotetta', f_checked: 'tarkistettu', f_candidates: 'ehdokasta',
  stalled_error: 'Tuotteiden haussa tapahtui virhe. Hyväksymäsi lista on tallessa.',
  stalled_reply: 'Aimo vastasi keskustelussa – mitään ei tilattu.', try_again: 'Yritä uudelleen', try_again_msg: 'Yritä uudelleen.',
  other: 'Muut', portions_n: '{n} annosta', from_recipe: 'Tallennetusta reseptistäsi', scaled: 'skaalattu {a} → {b} annosta',
  estimate: 'Aimon arvio – ei tallennettua reseptiä', saved_recipe: 'Tallennettu reseptiksesi', save_recipe: 'Tallenna reseptiksi',
  check_ingredients: 'Tarkista raaka-aineet', delivery_lc: 'toimitus', ingredient_ph: 'Raaka-aine', less: 'Vähemmän', more: 'Enemmän',
  remove: 'Poista', edited: 'Muokattu', add_ingredient: 'Lisää raaka-aine', nothing_ordered: 'Mitään ei ole vielä tilattu.',
  edits_one: '{n} muokkaus', edits_other: '{n} muokkausta', looks_right: 'Näyttää oikealta – etsi tuotteet',
  your_cart: 'Ostoskori', delivery: 'Toimitus', notes_n: 'Muistiinpanot ({n})', hide_notes: 'Piilota muistiinpanot', add_reference: 'Lisää viite',
  reference_ph: 'Viite, esim. lauantain juhlat', approved_by_you: 'Raaka-aineet hyväksytty',
  changes_one: '{n} muutos', changes_other: '{n} muutosta',
  not_available: 'Ei saatavilla', late: 'Myöhässä · {d}', in_stock: 'Varastossa', orderable: 'Tilattavissa', no_product: 'Tuotetta ei löytynyt',
  choose_one: 'Valitse yksi', replaces: 'Korvaa', your_usual: 'Tavallisesi', options_n: '{n} vaihtoehtoa', details: 'Tiedot',
  same_price: 'sama hinta', delivery_d: 'Toimitus {d}', estimate_paren: '(arvio)', order_by: 'Tilattava viimeistään {d}',
  co2: '{n} kg CO₂', in_stock_n: 'Varastossa ({n})', contains: 'Sisältää: {list}', notify_ok: 'Ilmoitamme sinulle ✓',
  notify_me: 'Ilmoita kun {name} on taas saatavilla', excl_vat: 'alv 0 %', incl_vat: '{x} sis. alv', per_portion: '{x} / annos',
  choose_first_one: 'Valitse ensin {n} vaihtoehto', choose_first_other: 'Valitse ensin {n} vaihtoehtoa', cutoff_passed: 'Tilausaika umpeutunut',
  confirm_before: 'Vahvista viimeistään {d}', in_dur: '{d} jäljellä', send_approval: 'Lähetä hyväksyttäväksi', confirm_order: 'Vahvista tilaus',
  order_confirmed: 'Tilaus vahvistettu', waiting_for: 'Odottaa hyväksyntää: {who}', your_approver: 'hyväksyjäsi', order_rejected: 'Tilausta ei hyväksytty',
  ref_r: 'Viite {r}', signed_valio: 'Valion allekirjoittama', new_order: 'Uusi tilaus', products_n: '{n} tuotetta',
  saved_template: 'Tallennettu tilauspohjaksi', save_template: 'Tallenna tilauspohjaksi', save: 'Tallenna',
  appr_title: 'Hyväksynnät', appr_sub: 'Asiakkaan oman rajan ylittävät tilaukset odottavat täällä ostovaltuutuksessa nimettyä henkilöä. Mitään ei lähetetä varastolle ennen päätöstä.',
  needs_approval: 'Odottaa hyväksyntääsi', via_aimo: 'Aimo-avustajan kautta', ordered_by: 'Tilaaja: {name}', order: 'Tilaus',
  lines_one: '{n} rivi', lines_other: '{n} riviä', why_needs: 'Miksi tarvitaan hyväksyntäsi', above_limit: 'Ylittää asiakkaan hyväksymisrajan.',
  note_ph: 'Lisää viesti keittiölle (valinnainen)', reject: 'Hylkää', approve: 'Hyväksy',
  audit_note: 'Päätöksesi tallentuu muuttumattomaan lokiin; hyväksynnän jälkeen Valio allekirjoittaa tilausvahvistuksen.',
  appr_empty: 'Ei odottavia hyväksyntöjä', appr_empty_body: 'Kun tilaus ylittää asiakkaan rajan tai vaatii toisen katseen, se näkyy täällä selkokielisin perustein.',
  vv_kicker: 'Valio Aimo – sisäinen', vv_title: 'Mitä avustaja kertoo Valiolle',
  vv_sub: 'Jokainen asiakkaan ostoskorissa hyväksymä korvaava tuote ja valinta on signaali Valion ostoille ja valikoimalle – samoin saatavuusilmoitukset ja kysyntä, jota valikoima ei pystynyt täyttämään.',
  kpi_orders: 'Tilaukset', kpi_via: '{n} Aimo-avustajan kautta', kpi_value: 'Vahvistettu arvo', kpi_confirmed: '{n} vahvistettu · alv 0 %',
  kpi_subs: 'Hyväksytyt korvaavat', kpi_subs_sub: '{a} saatavuusilmoitusta · {b} täyttämätöntä', kpi_audit: 'Lokin eheys',
  chain_ok: 'Ketju eheä', chain_broken: 'Ketju rikki', chain_n: '{n} tiivisteketjun merkintää tarkistettu',
  signals: 'Signaalit Valio Aimolle', recent_orders: 'Viimeisimmät tilaukset',
  signals_empty: 'Ei vielä signaaleja. Kun asiakas vahvistaa ostoskorin, jossa hän hyväksyy korvaavan tuotteen tai valitsee toisen vaihtoehdon, se näkyy täällä.',
  th_customer: 'Asiakas', th_channel: 'Kanava', th_status: 'Tila', th_total: 'Summa', ch_shop: 'Verkkokauppa · Aimo', ch_api: 'API-agentti',
  no_orders: 'Ei vielä tilauksia', sig_sub: 'Korvaava hyväksytty', sig_pref: 'Valinta', sig_notify: 'Saatavuusilmoitus',
  sig_unmet: 'Täyttämätön kysyntä', sig_notify_body: 'Asiakas haluaa tietää, kun tuote on taas saatavilla.',
  sig_unmet_body: 'valikoimasta ei löytynyt sopivaa.', needed_by: 'tarvitaan {d} mennessä',
  st_confirmed: 'Vahvistettu', st_pending: 'Odottaa hyväksyntää', st_rejected: 'Hylätty',
  tab_break: 'Yritä murtaa', bi_title: 'Yritä murtaa portti',
  bi_sub: 'Jokainen painike panee vilpillisen agentin lähettämään portille jotain, mitä asiakas ei ole allekirjoittanut. Mukana ei ole kielimallia eikä API-avainta: näet, mitä portti vastasi ja mitkä lokirivit se kirjoitti.',
  bi_scratch: 'Yritykset ajetaan portin erillisessä kopiossa: sama koodi, tuoteluettelo ja Valio-yhteys, oma tilauskirja. Asiakkaan tilaukset eivät muutu.',
  bi_run: 'Aja', bi_again: 'Aja uudelleen', bi_run_all: 'Aja kaikki', bi_running: 'Ajetaan…', bi_ms: '{n} ms',
  bi_steps: 'Mitä agentti lähetti', bi_answer: 'Mitä portti vastasi', bi_audit: 'Portin kirjoittamat lokirivit', bi_no_audit: 'Lokirivejä ei kirjoitettu.',
  bi_stopped: 'Pysäytetty', bi_not_stopped: 'Ei pysäytetty', bi_v_refused: 'Evätty', bi_v_blocked: 'Estetty', bi_v_held: 'Jäi odottamaan hyväksyntää', bi_v_detected: 'Havaittu',
  bi_tally: '{a}/{n} yritystä pysäytetty', bi_load_err: 'Yrityksiä ei voitu ladata', bi_run_err: 'Yritystä ei voitu ajaa', bi_empty: 'Tällä palvelimella ei ole ajettavia yrityksiä.',
  nokey_title: 'Avustaja tarvitsee ANTHROPIC_API_KEY-avaimen .env-tiedostoon.', nokey_body: 'Portti itse toimii ilman sitä.',
  err_session_lost: 'Palvelin käynnistyi uudelleen', err_session_lost_body: 'Uusi keskustelu on avattu. Jo tehdyt tilaukset säilyvät; lähetä pyyntösi uudelleen.',
  prefs_title: 'Asetukset', prefs_for: 'Näin Aimo-avustaja ostaa asiakkaalle {name}.',
  prefs_explainer: 'Aimo-avustaja noudattaa näitä asetuksia. Ne allekirjoitetaan ostovaltuutukseesi, jonka Valio tarkistaa jokaisen tilauksen yhteydessä.',
  prio_title: 'Mikä sinulle on tärkeää', prio_hint: 'Tärkeysjärjestyksessä. Avustaja järjestää vaihtoehdot näiden mukaan.', add_priority: 'Lisää painopiste',
  allergens_title: 'Vältettävät allergeenit', allergens_hint: 'Näitä sisältäviä tuotteita ei koskaan lisätä ostoskoriin. Tuotteet ilman allergeenitietoja merkitään.',
  none: 'Ei mitään', allergen_ph: 'esim. seesami', remove_x: 'Poista {x}', limit_title: 'Hyväksymisraja', limit_hint: 'Tämän ylittävät tilaukset hyväksyy {who}.',
  per_order: 'tilausta kohden, alv 0 %', templates_title: 'Tilauspohjat',
  auto_confirm: 'Vahvista tilauspohjani automaattisesti, kun kaikki on saatavilla', save_prefs: 'Tallenna asetukset',
  recipes_title: 'Reseptisi', recipes_hint: 'Aimo skaalaa nämä pyytämääsi annosmäärään. Tallenna uusia raaka-ainelistasta.',
  no_recipes: 'Ei vielä tallennettuja reseptejä.',
  just_now: 'juuri nyt', min_ago: '{n} min sitten', h_ago: '{n} h sitten', days: '{n} päivää',
}

const DICT: Record<Lang, Record<Key, string>> = { en, fi }

export function t(key: Key, vars?: Record<string, string | number>): string {
  let s = DICT[current][key] ?? en[key]
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

/** Plural: t(`${base}_one`) for 1, else t(`${base}_other`). */
export function tn(one: Key, other: Key, n: number, vars?: Record<string, string | number>): string {
  return t(n === 1 ? one : other, { n: fNum(n), ...vars })
}

// ------------------------------------------------------------------ formatting
const loc = () => (current === 'fi' ? 'fi-FI' : 'en-GB')
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function fEur(v: unknown, whole = false): string {
  if (!isNum(v)) return '—'
  return new Intl.NumberFormat(loc(), { style: 'currency', currency: 'EUR', minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 }).format(v)
}

export function fNum(v: unknown): string {
  return isNum(v) ? new Intl.NumberFormat(loc(), { maximumFractionDigits: 2 }).format(v) : '—'
}

/** "2026-11-20" → "Fri 20 Nov" / "pe 20.11." */
export function fDay(v: unknown): string {
  if (typeof v !== 'string' || !v) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v)
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return current === 'fi'
    ? d.toLocaleDateString('fi-FI', { weekday: 'short', day: 'numeric', month: 'numeric' }).replace(/\.?$/, '.')
    : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function fAgo(v: unknown): string {
  if (typeof v !== 'string') return ''
  const ms = Date.now() - new Date(v).getTime()
  if (Number.isNaN(ms)) return ''
  const s = Math.round(ms / 1000)
  if (s < 45) return t('just_now')
  if (s < 3600) return t('min_ago', { n: Math.round(s / 60) })
  if (s < 86400) return t('h_ago', { n: Math.round(s / 3600) })
  return fDay(v.slice(0, 10))
}

const FI_DAYS: Record<string, string> = { Monday: 'ma', Tuesday: 'ti', Wednesday: 'ke', Thursday: 'to', Friday: 'pe', Saturday: 'la', Sunday: 'su' }
export function fWeekdays(days: string[]): string {
  return days.map((d) => (current === 'fi' ? FI_DAYS[d] || d : d.slice(0, 3))).join('/')
}

export function fUnit(u: string | undefined): string {
  if (!u || u === 'unit' || u === 'pcs') return current === 'fi' ? 'kpl' : 'pcs'
  return u
}

/** Product name in the current language (Valio's Finnish name where it has one). */
export function pname(o: { name?: string; name_fi?: string | null } | null | undefined): string {
  if (!o) return ''
  return (current === 'fi' && o.name_fi) || o.name || ''
}

const NOTE_FI: Record<string, string> = {
  CUTOFF_PASSED: 'Tilauksen katkaisuaika on mennyt – toimituspäivä on arvio',
  LATE: 'Saapuu pyydetyn päivän jälkeen',
  PARTIAL_STOCK: 'Varastossa vain osa määrästä',
  LOW_RELIABILITY: 'Toimitusvarmuus heikko',
  ALLERGEN_DATA_MISSING: 'Allergeenitiedot puuttuvat',
  CONTENT_MISMATCH: 'Pakkauskoko tarkistettu Valion hinnasta',
  LOT_SIZE: 'Tilattava tasaerinä',
  SALES_BLOCK: 'Tuote on myyntiestossa',
  NOT_DELIVERABLE: 'Ei toimitettavissa pyydettynä päivänä',
  OUT_OF_STOCK: 'Loppu varastosta',
  NO_PRICE: 'Hintaa ei saatavilla',
  UNIT_UNKNOWN: 'Myyntiyksikkö epäselvä – tarkista määrä',
}

/** Option notes: Finnish texts from the engine's codes in FI mode, else the English messages. */
export function noteTexts(o: { notes?: string[]; note_codes?: string[] }): string[] {
  const notes = o.notes || []
  if (current !== 'fi') return notes
  return notes.map((n, i) => NOTE_FI[o.note_codes?.[i] || ''] || n)
}

/** Server unit prices come as "€2.23/kg"; in Finnish show "2,23 €/kg". */
export function fPricePer(v: string | null | undefined): string | null {
  if (!v) return null
  const m = /^€([\d.]+)\/(\S+)$/.exec(v)
  if (!m || current !== 'fi') return v
  return `${new Intl.NumberFormat('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(m[1]))} €/${m[2]}`
}
