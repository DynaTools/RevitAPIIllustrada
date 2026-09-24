# -*- coding: utf-8 -*-
"""Didactic explanations for the Rec Sessione guides (Italian).

COMANDI keys are Revit transaction names exactly as logged in
steps.jsonl (language of the Revit UI, '&' accelerators removed).
FINESTRE keys are raw dialog ids (the `dialog_id` field in steps.jsonl).

Unknown commands are listed at the end of each generated README —
add them here and regenerate; the guide improves with every session.
"""

COMANDI = {
    u"Reference Plane": {
        "titolo": u"Piano di riferimento",
        "testo": (
            u"Crea un piano di riferimento: l'ossatura invisibile della "
            u"famiglia. La geometria non si disegna 'a mano libera' — si "
            u"aggancia ai piani di riferimento, che ne guidano il "
            u"comportamento parametrico."),
    },
    u"Place Dimensions": {
        "titolo": u"Quota",
        "testo": (
            u"Inserisce una quota. Nell'editor delle famiglie le quote non "
            u"sono semplici annotazioni: bloccate o etichettate con un "
            u"parametro diventano i vincoli che pilotano la geometria."),
    },
    u"Toggle EQ": {
        "titolo": u"Vincolo di uguaglianza (EQ)",
        "testo": (
            u"Attiva il vincolo di uguaglianza sulla quota: i segmenti "
            u"restano sempre uguali tra loro e la geometria rimane centrata "
            u"quando le dimensioni cambiano."),
    },
    u"Toggle Lock": {
        "titolo": u"Blocco del vincolo",
        "testo": (
            u"Chiude il lucchetto su un allineamento o una quota: la "
            u"relazione viene mantenuta anche quando il modello cambia. "
            u"È il gesto che trasforma un disegno in un sistema di regole."),
    },
    u"Modify element attributes": {
        "titolo": u"Modifica delle proprietà",
        "testo": (
            u"Modifica le proprietà degli elementi selezionati — ad esempio "
            u"l'etichettatura di una quota con un parametro o un cambio "
            u"nella tavolozza Proprietà."),
    },
    u"Add Parameter": {
        "titolo": u"Nuovo parametro",
        "testo": (
            u"Crea un parametro di famiglia: da qui in poi quel valore non "
            u"è più un numero fisso ma una variabile, modificabile per ogni "
            u"tipo o istanza."),
    },
    u"Solid Extrusion": {
        "titolo": u"Estrusione solida",
        "testo": (
            u"Avvia un'estrusione solida: si disegna un profilo 2D in uno "
            u"sketch e Revit lo estrude perpendicolarmente al piano di "
            u"lavoro."),
    },
    u"Create Sketch": {
        "titolo": u"Creazione dello sketch",
        "testo": (
            u"Apre la modalità sketch: un ambiente di disegno 2D protetto "
            u"in cui si definisce il profilo della geometria."),
    },
    u"Line - Rectangle": {
        "titolo": u"Rettangolo",
        "testo": (
            u"Disegna un rettangolo di linee nello sketch attivo. Notare le "
            u"quote automatiche di sketch che Revit aggiunge da solo."),
    },
    u"Finish sketch": {
        "titolo": u"Fine sketch",
        "testo": (
            u"Conclude lo sketch: Revit valida il profilo (chiuso, senza "
            u"intersezioni) e genera la geometria solida."),
    },
    u"Family type": {
        "titolo": u"Tipo di famiglia",
        "testo": (
            u"Operazione sui tipi di famiglia: creazione o cambio del tipo "
            u"corrente."),
    },
    u"Family Types": {
        "titolo": u"Applicazione dei tipi di famiglia",
        "testo": (
            u"Applica i valori definiti nella finestra Tipi di famiglia: è "
            u"il 'flex test' — si cambiano i parametri e si verifica che la "
            u"geometria segua senza rompersi."),
    },
    u"Wall - Line": {
        "titolo": u"Muro (tracciato lineare)",
        "testo": u"Crea un muro disegnandone il tracciato con una linea.",
    },
    u"Room": {
        "titolo": u"Locale",
        "testo": (
            u"Inserisce un locale (room): Revit ne calcola area e "
            u"perimetro a partire dagli elementi che lo delimitano."),
    },
    u"Delete Selection": {
        "titolo": u"Eliminazione",
        "testo": u"Elimina gli elementi selezionati.",
    },
    u"Copy": {
        "titolo": u"Copia",
        "testo": u"Copia gli elementi selezionati in una nuova posizione.",
    },
    u"Drag": {
        "titolo": u"Trascinamento",
        "testo": (
            u"Modifica diretta trascinando l'elemento o i suoi grip con il "
            u"mouse."),
    },
    u"Drag refplane model end": {
        "titolo": u"Trascinamento del piano di riferimento",
        "testo": (
            u"Allunga o sposta l'estremità di un piano di riferimento "
            u"trascinandola."),
    },
}

FINESTRE = {
    "Dialog_Revit_ParamPropertiesFamily": {
        "titolo": u"Finestra: Proprietà del parametro",
        "testo": (
            u"La finestra di creazione/modifica di un parametro: nome, "
            u"disciplina, tipo di dato, raggruppamento e la scelta cruciale "
            u"tra parametro di tipo e di istanza."),
    },
    "Dialog_Family_FamilyType": {
        "titolo": u"Finestra: Tipi di famiglia",
        "testo": (
            u"La cabina di regia della famiglia: per ogni tipo si "
            u"impostano valori, formule e blocchi dei parametri."),
    },
    "Dialog_Revit_Name": {
        "titolo": u"Finestra: Nome",
        "testo": u"Assegnazione del nome (ad esempio per un nuovo tipo).",
    },
    "TaskDialog": {
        "titolo": u"Avviso di Revit",
        "testo": u"",
    },
}
