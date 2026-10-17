# Doctor verify

How a diagnosis file opens for a doctor without a clinic contract, and stays unreadable in the patient app.

Clario has two parts. The patient keeps a diary and lab facts. Conclusions (a diagnosis, a previous opinion, condition names, the Diagnosi / Conclusioni / Impression block that OCR reads off a letter) are a separate file. The patient app never renders that file.

## Two files

| File | Holds | Who can open it |
|---|---|---|
| Facts | Diary, quotes, lab numbers | Patient, always |
| Conclusions | OCR diagnosis band, previous opinion, condition names | Doctor session only |

The patient keeps using the diary and can send it to any doctor. The diagnosis never sits in a file their app can render.

## At import

Detect the Diagnosi / Conclusioni / Impression block on an uploaded letter. Store a redacted page for the patient. Keep the intact page only inside the sealed conclusions blob.

The patient API returns who and when for a previous opinion, never the diagnosis text and never a condition name. `GET /api/care` already does this. Uploaded letters do not yet: stripping those sections is still roadmap (pitch Q13).

## At the visit

There is no clinic install and no partner list.

1. The doctor opens the link on their phone.
2. They type name, surname, and province. That is what the public search uses. The Ordine number is per province, so the same number exists in Milan and in Rome. An Ordine number alone is not a national key.
3. The hit comes back as a line such as "Rossi Maria, Ordine di Milano, Albo medici chirurghi".
4. The patient sees that name on their own screen and taps Confirm. That tap releases the conclusions blob to the doctor's tab for this session.
5. The patient build has no release call. Closing the tab drops the key.

For a pilot, step 3 is a person checking the public site. An automated lookup would mean scraping a site that sits behind a bot wall, or a PDND agreement with FNOMCeO. That agreement is with the federation, still not a contract with each clinic.

## The register

[Albo Unico](https://albounico.fnomceo.it/) is a public search page. Anyone can look up a medico chirurgo or an odontoiatra. Provincial orders send the data. FNOMCeO publishes it so a person can check that someone is enrolled.

The machine API (lookup by codice fiscale) sits on PDND. Callers are public administrations and the Ordini, under a federation agreement. Clario cannot call it.

| On the register | Missing |
|---|---|
| Medici chirurghi and odontoiatri currently enrolled in an Ordine provinciale | Suspended, struck off, or mid-transfer between provinces |
| Data the province has already sent | Lag while a province has not updated |
| | Nurses and other professions (other federations) |
| | A foreign doctor with no Italian enrollment |

Practising medicine in Italy requires that enrollment, so a practising Italian doctor should be there, apart from the transfer gap and the update lag. Professionals mid-transfer are not shown. The enrollment date on the register is the current enrollment, not the first one.

## What a match proves

The name is on the albo. It does not prove the person holding the phone is that doctor. A patient can type someone else's name.

The patient's Confirm, with the register name in front of them, is the check that the right person is in the room. The open is logged under that register hit. A later lock, still with no clinic contract, is a one-time code sent to the contact published for that doctor.

## What is already in the app

A working demo of the visit flow: "Show a doctor in the room" on the patient's Share screen starts a session and shows a link and QR; the doctor's page (`/doctor/:code`, no vault) looks up name, surname and province in a demo register of synthetic doctors, the patient confirms the register line, and only then does the doctor's tab receive the previous opinion (`backend/clario/doctor_verify.py`, endpoints in `docs/API.md`). The doctor's token lives only in that tab; closing it or "End" ends the session, and every step is in the session log.

Condition names never go to patient screens. A second opinion hides the previous doctor's conclusions until the new doctor signs (`backend/clario/second_opinion.py`). The gap is the scanned letter: the patient still holds the original page, and that page can contain the diagnosis.
