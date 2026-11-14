"""Texts the webshop assistant writes itself (not the AI), in English and Finnish."""
from __future__ import annotations

from datetime import date

LANGS = ("en", "fi")

_FI_DAYS = ["ma", "ti", "ke", "to", "pe", "la", "su"]

TEXT: dict[str, dict[str, str]] = {
    "greeting": {
        "en": "Hi {name}! Tell me what you're cooking, or give me a shopping list. You approve every step "
              "before anything is ordered.",
        "fi": "Hei {name}! Kerro mitä olet valmistamassa tai anna ostoslista. Hyväksyt jokaisen vaiheen "
              "ennen kuin mitään tilataan.",
    },
    "busy": {"en": "The assistant is still working on your previous message.",
             "fi": "Avustaja käsittelee vielä edellistä viestiäsi."},
    "wait": {"en": "Please wait a moment.", "fi": "Hetki vielä."},
    "empty": {"en": "Message is empty.", "fi": "Viesti on tyhjä."},
    "no_question": {"en": "There is no open question.", "fi": "Avoimia kysymyksiä ei ole."},
    "answer_all": {"en": "Please answer: {missing}", "fi": "Vastaa vielä: {missing}"},
    "no_plan": {"en": "There is no ingredient list waiting for approval.",
                "fi": "Hyväksyttävää raaka-ainelistaa ei ole."},
    "empty_plan": {"en": "The list is empty.", "fi": "Lista on tyhjä."},
    "no_cart": {"en": "There is no cart yet.", "fi": "Ostoskoria ei ole vielä."},
    "nothing_to_order": {"en": "There is nothing to order.", "fi": "Tilattavaa ei ole."},
    "choice_needed": {"en": "Please choose a product for: {lines}", "fi": "Valitse tuote riveille: {lines}"},
    "plan_approved": {"en": "Ingredients approved", "fi": "Raaka-aineet hyväksytty"},
    "plan_changes": {"en": " ({n} change{s})", "fi": " ({n} muutos{s})"},
    "recipe_saved": {"en": "Saved as your recipe: {names}", "fi": "Tallennettu reseptiksesi: {names}"},
    "several_questions": {"en": "A few quick questions", "fi": "Muutama nopea kysymys"},
    "drafted": {"en": "Drafted {n} ingredients", "fi": "Laadin {n} raaka-ainetta"},
    "from_recipe": {"en": "from your saved recipe {names}", "fi": "tallennetusta reseptistäsi {names}"},
    "estimate_for": {"en": "my estimate for {names}", "fi": "oma arvioni: {names}"},
    "check_list": {"en": "Check the quantities, change anything, then I'll find the products.",
                   "fi": "Tarkista määrät ja muuta tarvittaessa, sitten etsin tuotteet."},
    "cart_ready": {"en": "Your cart is ready to review.", "fi": "Ostoskorisi on valmis tarkistettavaksi."},
    "built_cart": {"en": "Built the cart: {n} lines, prices and stock checked live",
                   "fi": "Ostoskori koottu: {n} riviä, hinnat ja saatavuus tarkistettu"},
    "read_profile": {"en": "Read your profile: {recipes} recipes, {usual} usual products",
                     "fi": "Luin profiilisi: {recipes} reseptiä, {usual} vakiotuotetta"},
    "tool_context": {"en": "Reading your profile", "fi": "Luen profiiliasi"},
    "tool_find": {"en": "Searching Valio Aimo's catalog", "fi": "Haen Valio Aimon valikoimasta"},
    "tool_offers": {"en": "Checking live price and stock", "fi": "Tarkistan hinnat ja saatavuuden"},
    "tool_product": {"en": "Reading product details", "fi": "Luen tuotetietoja"},
    "funnel": {"en": "Searched {catalog} products → {live} checked live → {short} candidates",
               "fi": "Haettu {catalog} tuotteesta → {live} tarkistettu → {short} ehdokasta"},
    "too_many_steps": {"en": "I couldn't finish this request in a reasonable number of steps.",
                       "fi": "En saanut pyyntöä valmiiksi kohtuullisessa ajassa."},
    "went_wrong": {"en": "Something went wrong: {err}", "fi": "Jokin meni pieleen: {err}"},
    "order_failed": {"en": "Valio could not take this order yet: {msg}",
                     "fi": "Valio ei voinut vielä ottaa tilausta vastaan: {msg}"},
    "order_confirmed": {"en": "Order {id} is confirmed: {total} excl. VAT, delivery {day}. Valio has signed "
                              "the confirmation.",
                        "fi": "Tilaus {id} on vahvistettu: {total} alv 0 %, toimitus {day}. Valio on "
                              "allekirjoittanut vahvistuksen."},
    "order_pending": {"en": "Sent to {who} for approval: {reasons}",
                      "fi": "Lähetetty hyväksyttäväksi: {who}. {reasons}"},
    "order_rejected": {"en": "Valio could not accept this order: {reasons}",
                       "fi": "Valio ei voinut hyväksyä tilausta: {reasons}"},
    "your_approver": {"en": "your approver", "fi": "hyväksyjäsi"},
    "approval_decided": {"en": "{who} {verb} order {id}.", "fi": "{who} {verb} tilauksen {id}."},
    "approved_verb": {"en": "approved", "fi": "hyväksyi"},
    "rejected_verb": {"en": "rejected", "fi": "hylkäsi"},
    "approver_note": {"en": " Note: “{note}”", "fi": " Huomautus: ”{note}”"},
    "check_template": {"en": "Check my order template “{name}” for the next delivery.",
                       "fi": "Tarkista tilauspohjani ”{name}” seuraavaan toimitukseen."},
    "template_checked": {"en": "Checked {n} order-template items for {day}: {ok} available, {bad} with problems.",
                         "fi": "Tarkistettu {n} tilauspohjan tuotetta toimitukseen {day}: {ok} saatavilla, "
                               "{bad} ongelmallista."},
    "template_auto": {"en": "Everything in “{name}” is available, so I confirmed it automatically as your "
                            "settings allow: {total}, delivery {day}.",
                      "fi": "Kaikki tilauspohjan ”{name}” tuotteet ovat saatavilla, joten vahvistin tilauksen "
                            "automaattisesti asetustesi mukaan: {total}, toimitus {day}."},
    "template_ok": {"en": "Everything is available. Review the cart and confirm when ready.",
                    "fi": "Kaikki on saatavilla. Tarkista ostoskori ja vahvista kun olet valmis."},
    "template_saved": {"en": "Saved as order template “{name}” ({n} products).",
                       "fi": "Tallennettu tilauspohjaksi ”{name}” ({n} tuotetta)."},
    "chk_hard": {"en": "Above the {amount} maximum for one order", "fi": "Ylittää tilauksen enimmäismäärän {amount}"},
    "chk_over": {"en": "Above your {amount} limit: {who} approves",
                 "fi": "Ylittää rajasi {amount}: {who} hyväksyy"},
    "chk_within": {"en": "Within your {amount} order limit", "fi": "Tilausrajasi {amount} sisällä"},
    "chk_allergen_bad": {"en": "{n} product(s) conflict with your allergen rules",
                         "fi": "{n} tuote(tta) on ristiriidassa allergeenisääntöjesi kanssa"},
    "chk_allergen_nodata": {"en": "{n} without allergen data: {who} approves",
                            "fi": "{n} ilman allergeenitietoja: {who} hyväksyy"},
    "chk_allergen_ok": {"en": "Allergen rules met: no {list}", "fi": "Allergeenisäännöt täyttyvät: ei {list}"},
    "chk_late": {"en": "{n} item(s) arrive after {day}", "fi": "{n} tuote(tta) saapuu {day} jälkeen"},
    "chk_on_time": {"en": "Everything arrives by {day}", "fi": "Kaikki saapuu viimeistään {day}"},
    "replaces_note": {"en": "Customer's own words", "fi": "Asiakkaan omin sanoin"},
}


def t(lang: str, key: str, **kw) -> str:
    entry = TEXT[key]
    return entry.get(lang if lang in LANGS else "en", entry["en"]).format(**kw)


def day(iso: str | None, lang: str = "en") -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso[:10])
    if lang == "fi":
        return f"{_FI_DAYS[d.weekday()]} {d.day}.{d.month}."
    return f"{d:%a} {d.day} {d:%b}"


def eur(x: float, lang: str = "en", decimals: int = 2) -> str:
    s = f"{x:,.{decimals}f}"
    if lang == "fi":
        return s.replace(",", " ").replace(".", ",") + " €"
    return "€" + s


LANGUAGE_RULE = {
    "en": "Write every text you show (questions, answer options, titles, dish and ingredient names, "
          "'why', messages) in English.",
    "fi": "The customer uses the webshop in FINNISH. Write every text you show (questions, answer options, "
          "titles, dish and ingredient names, assumptions, 'why', messages) in natural professional Finnish. "
          "find_products queries stay in short ENGLISH words (the catalog search maps them to Finnish).",
}
