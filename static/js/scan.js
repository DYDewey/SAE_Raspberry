// Bouton "Scanner la carte" : le serveur attend le prochain bip du boîtier choisi.
//   data-scan="ID étudiant" : la carte est associée directement à l'étudiant, puis la page se recharge.
//   data-scan="0" + data-cible="id du champ" : l'UID est seulement recopié dans le champ du formulaire.
(function () {
    const modalEl = document.getElementById('modal-scan');
    if (!modalEl) return;
    const modal = new bootstrap.Modal(modalEl);
    const choixBoitier = document.getElementById('scan-boitier');
    const champ = nom => modalEl.querySelector(`[data-champ="${nom}"]`);
    const action = nom => modalEl.querySelector(`[data-action="${nom}"]`);
    let minuterie = null, bouton = null, uidConflit = null;

    function afficher(etat) {
        modalEl.querySelectorAll('[data-etat]').forEach(b => b.hidden = b.dataset.etat !== etat);
        action('reessayer').hidden = etat !== 'expire';
        action('reconnecter').hidden = etat !== 'deconnecte';
        action('forcer').hidden = etat !== 'conflit';
        action('annuler').textContent = etat === 'attente' ? 'Annuler' : 'Fermer';
    }

    function arreter() {
        clearInterval(minuterie);
        minuterie = null;
    }

    // Session expirée : le serveur répond 401 au lieu de faire le travail
    function deconnecte(r) {
        if (r.status !== 401 && !r.redirected) return false;
        arreter();
        afficher('deconnecte');
        return true;
    }

    async function demarrer() {
        arreter();
        if (!choixBoitier.value || choixBoitier.disabled) {
            afficher('expire');
            return;
        }
        afficher('attente');
        champ('nom').textContent = bouton.dataset.nom || '';
        champ('boitier').textContent = choixBoitier.value;
        champ('restant').textContent = '60';
        champ('alerte').hidden = true;
        const corps = new FormData();
        corps.append('device_id', choixBoitier.value);
        corps.append('etudiant_id', bouton.dataset.scan || '0');
        let r;
        try {
            r = await fetch('/admin/scan/demarrer', { method: 'POST', body: corps });
        } catch (e) { afficher('expire'); return; }
        if (deconnecte(r)) return;
        if (!r.ok) { afficher('expire'); return; }
        minuterie = setInterval(verifier, 1000);
    }

    function terminer(uid) {
        if (bouton.dataset.cible) {                   // formulaire : on remplit le champ
            document.getElementById(bouton.dataset.cible).value = uid;
            setTimeout(() => modal.hide(), 1200);
        } else {                                      // liste : la carte est enregistrée
            setTimeout(() => window.location.reload(), 1200);
        }
    }

    async function verifier() {
        let r;
        try {
            const reponse = await fetch('/admin/scan/etat');
            if (deconnecte(reponse)) return;
            r = await reponse.json();
        } catch (e) { return; }                       // réseau momentanément indisponible : on réessaie
        if (r.statut === 'attente') {
            champ('restant').textContent = r.restant;
            champ('alerte').textContent = r.alerte || '';
            champ('alerte').hidden = !r.alerte;
            return;
        }
        arreter();
        if (r.statut === 'trouve') {
            champ('uid').textContent = r.uid;
            champ('message').textContent = r.message || '';
            afficher('trouve');
            terminer(r.uid);
        } else if (r.statut === 'conflit') {
            uidConflit = r.uid;
            champ('uid-conflit').textContent = r.uid;
            champ('proprietaire').textContent = r.proprietaire;
            champ('nom2').textContent = bouton.dataset.nom || '';
            afficher('conflit');
        } else {                                      // 'expire' ou 'aucun'
            afficher('expire');
        }
    }

    // Confirmation : la carte est retirée à l'autre étudiant et attribuée à celui-ci
    action('forcer').addEventListener('click', async () => {
        if (bouton.dataset.cible) {
            terminer(uidConflit);                     // le changement se fera à l'enregistrement du formulaire
            return;
        }
        const corps = new FormData();
        corps.append('nfc_uid', uidConflit);
        corps.append('retour', window.location.pathname + window.location.search);
        const r = await fetch(`/admin/etudiants/${bouton.dataset.scan}/carte`, { method: 'POST', body: corps });
        if (deconnecte(r)) return;
        window.location.reload();
    });

    document.querySelectorAll('[data-scan]').forEach(b => b.addEventListener('click', () => {
        bouton = b;
        modal.show();
        demarrer();
    }));

    choixBoitier.addEventListener('change', demarrer);    // changer de boîtier relance l'attente
    action('reessayer').addEventListener('click', demarrer);
    action('reconnecter').addEventListener('click', () => {
        const ici = window.location.pathname + window.location.search;
        window.location.href = '/login?suivant=' + encodeURIComponent(ici);
    });
    action('annuler').addEventListener('click', () => {
        if (minuterie) fetch('/admin/scan/annuler', { method: 'POST' });
        arreter();
        modal.hide();
    });
})();
