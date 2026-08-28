// Mapping editor and mowing lane preview UI.
// Loaded as a classic script so existing inline HTML handlers can call these functions.

// Shared map/editor state
var mapEditor = null;
var mapLayers = {};
var activeBaseLayer = 'osm';
var activeMapName = '';
var activeMapPayload = null;
var boundaryPoints = [];
var boundaryLine = null;
var boundaryMarkers = [];
var subMapLayers = [];
var lanePreviewLayers = [];
var lanePreviewLaneLayers = [];
var lanePreviewRestLayers = [];
var lanePreviewConnectorLayers = [];
var planBlockedMessage = null;
var planAlertDismissed = null;
// Winkelsperren, die der Plan-Check gemeldet hat. Muss wie planBlockedMessage
// festgehalten werden: die Statusabfrage baut die Zeile alle zwei Sekunden neu
// auf und hat die Warnung sonst überschrieben, bevor sie zu lesen war.
var planHeadingWarning = null;
var laneSimulationLayers = [];
var laneSimulationResult = null;
var laneSimulationRunning = false;
var laneSimulationTimer = null;
var laneSimulationAnimationFrame = null;
var laneSimulationPlayback = null;
var laneSimulationPaused = false;
var laneSimulationAbortController = null;
var laneSimulationMarker = null;
var laneSimulationFootprint = null;
var lanePreviewPlan = null;
var lanePreviewSource = 'none';
var laneProgressMarker = null;
var vehicleMarker = null;
var vehicleHeadingLine = null;
var latestVehiclePose = null;
var savedPlans = [];
var loadedPlanReady = false;
var rtkAvailable = false;
var planUiMode = 'map';
var activePlanName = '';
var planIsRunning = false;
var planResumeAvailable = false;
var planStartAttemptToken = 0;
var planLoadRunning = false;
// Der offene Plan gehoert dem Fahrzeug, nicht dem Browser. Wer sich waehrend
// einer Fahrt dazuschaltet - Plan am Handy gestartet, danach am PC
// nachgesehen (real 27.08.) - sah oben "Fahre Brunnen" und darunter "Kein Plan
// geladen": keine Bahnen auf der Karte, Abfahrposition 0 m / 0 m, leere
// Planauswahl. Jede Oberflaeche holt sich den laufenden Plan deshalb selbst
// nach, statt ihn nur beim Startklick zu kennen.
var latestPlanExecutionStatus = null;
var planAdoptedMapName = null;
var planAdoptionRunning = false;
var planAdoptionRetryAfter = 0;
var selectedPointIndex = null;
var manualPointDragIndex = null;

// Map initialization and base layers
function initMapEditor() {
    if (mapEditor || typeof L === 'undefined') return;

    mapEditor = L.map('mapEditor', {
        zoomControl: true,
        preferCanvas: true
    }).setView([53.332385, 11.078706], 19);

    mapLayers.osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxNativeZoom: 19,
        maxZoom: 22,
        attribution: '&copy; OpenStreetMap'
    });

    const BingLayer = L.TileLayer.extend({
        getTileUrl: function(coords) {
            const quad = tileToQuadKey(coords.x, coords.y, coords.z);
            const subdomain = Math.abs(coords.x + coords.y) % 4;
            return `https://ecn.t${subdomain}.tiles.virtualearth.net/tiles/a${quad}.jpeg?g=14328`;
        }
    });
    // maxNativeZoom ist am Standplatz nachgemessen, nicht geschaetzt: darueber
    // liefert der Dienst zwar HTTP 200, aber fuer jede Kachel dasselbe
    // Platzhalterbild. Mit der Angabe skaliert Leaflet die letzte echte
    // Zoomstufe hoch - unscharf, aber es zeigt die Flaeche. Ohne sie waere die
    // Karte beim Feinschliff auf Zoom 21/22 einfarbig grau.
    //
    // Esri (ArcGIS World_Imagery) stand hier als zweite Luftbildquelle und ist
    // wieder entfallen: sein Bild endet an dieser Stelle schon bei Zoom 19 und
    // war auf den Planungsstufen nur noch hochskalierter Brei. Zwei Quellen
    // lohnen sich erst, wenn die zweite auch etwas zeigt.
    mapLayers.bing = new BingLayer('', {
        maxNativeZoom: 20,
        maxZoom: 22,
        attribution: '&copy; Microsoft Bing'
    });

    setMapBaseLayer(loadPreferredBaseLayer());

    document.addEventListener('mousemove', handleManualPointDrag);
    document.addEventListener('mouseup', finishManualPointDrag);
}

function tileToQuadKey(x, y, z) {
    let quad = '';
    for (let i = z; i > 0; i--) {
        let digit = 0;
        const mask = 1 << (i - 1);
        if ((x & mask) !== 0) digit += 1;
        if ((y & mask) !== 0) digit += 2;
        quad += digit.toString();
    }
    return quad;
}

// Kartenhintergruende und die Knoepfe, die sie schalten.
var BASE_LAYER_BUTTONS = {
    osm: 'osmLayerBtn',
    bing: 'bingLayerBtn'
};
var BASE_LAYER_STORAGE_KEY = 'ugv.mapBaseLayer';

function loadPreferredBaseLayer() {
    // Die Wahl ueberlebt das Neuladen. Wer auf dem Feld steht und den Plan
    // gegen das Luftbild prueft, will nach jedem Seitenwechsel nicht erneut
    // umschalten.
    try {
        const gespeichert = window.localStorage.getItem(BASE_LAYER_STORAGE_KEY);
        // Wer zuletzt Esri gewaehlt hatte, wollte ein Luftbild und keine
        // Strassenkarte. Den entfallenen Namen deshalb auf Bing umbiegen,
        // statt still auf OSM zurueckzufallen.
        if (gespeichert === 'esri') return 'bing';
        if (gespeichert && BASE_LAYER_BUTTONS[gespeichert]) return gespeichert;
    } catch (e) {
        // Privates Fenster oder gesperrter Speicher - dann eben OSM.
    }
    return 'osm';
}

function setMapBaseLayer(layerName) {
    initMapEditor();
    if (!mapEditor || !mapLayers[layerName]) return;
    if (mapLayers[activeBaseLayer] && mapEditor.hasLayer(mapLayers[activeBaseLayer])) {
        mapEditor.removeLayer(mapLayers[activeBaseLayer]);
    }
    activeBaseLayer = layerName;
    mapLayers[layerName].addTo(mapEditor);
    // Der Hintergrund gehoert unter alles andere. Ohne das legt sich eine
    // spaeter zugeschaltete Kachelebene ueber Grenze, Bahnen und Fahrzeug.
    if (mapLayers[layerName].bringToBack) mapLayers[layerName].bringToBack();

    Object.keys(BASE_LAYER_BUTTONS).forEach(function(name) {
        const btn = document.getElementById(BASE_LAYER_BUTTONS[name]);
        if (btn) btn.classList.toggle('primary', name === layerName);
    });

    try {
        window.localStorage.setItem(BASE_LAYER_STORAGE_KEY, layerName);
    } catch (e) {
        // Nicht speichern zu koennen ist kein Grund, die Karte nicht zu zeigen.
    }
}

// Map list, loading, and boundary editing
function refreshMapList() {
    const mainOnly = document.getElementById('mainMapsOnlyToggle')?.checked;
    const url = mainOnly ? '/api/mapping/maps?main_only=1' : '/api/mapping/maps';
    return fetch(url)
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('mapSelect');
            const current = select.value || activeMapName;
            select.innerHTML = '<option value="">Keine Karte gewählt</option>';
            (data.maps || []).forEach(item => {
                const option = document.createElement('option');
                option.value = item.name;
                option.textContent = item.name;
                select.appendChild(option);
            });
            if (current && (data.maps || []).some(item => item.name === current)) {
                select.value = current;
            }
            return data.maps || [];
        });
}

function toggleMainMapsOnly() {
    clearMapAnalysis();
    refreshMapList().then(() => {
        const selected = document.getElementById('mapSelect').value;
        if (selected) loadMap(selected);
    });
}

function loadSelectedMap() {
    const name = document.getElementById('mapSelect').value;
    if (!name) {
        clearMapEditor();
        return;
    }
    loadMap(name);
}

function loadMap(name) {
    initMapEditor();
    return fetch(`/api/mapping/maps/${encodeURIComponent(name)}`)
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            if (!result.ok || result.data.success === false) {
                setMapEditorStatus(result.data.error || 'Karte konnte nicht geladen werden');
                return false;
            }
            activeMapName = result.data.name;
            activeMapPayload = result.data.map;
            boundaryPoints = boundaryPointsFromGeoJSON(activeMapPayload);
            selectedPointIndex = null;
            clearMapAnalysis();
            renderBoundaryEditor();
            setMapEditorStatus(`${activeMapName}: ${boundaryPoints.length} Punkte`);
            loadMapAnalysis(activeMapName);
            refreshPlanList();
            return true;
        });
}

function boundaryPointsFromGeoJSON(payload) {
    const feature = (payload.features || []).find(item => item.properties && item.properties.type === 'boundary');
    if (!feature || !feature.geometry || feature.geometry.type !== 'Polygon') return [];
    const ring = (feature.geometry.coordinates || [[]])[0] || [];
    const openRing = ring.length > 1 && sameCoordinate(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
    return openRing.map(coord => ({latitude: Number(coord[1]), longitude: Number(coord[0])}));
}

function sameCoordinate(a, b) {
    return Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && a[1] === b[1];
}

function renderBoundaryEditor() {
    initMapEditor();
    boundaryMarkers.forEach(marker => marker.remove());
    boundaryMarkers = [];
    if (boundaryLine) boundaryLine.remove();

    const latLngs = boundaryPoints.map(point => [point.latitude, point.longitude]);
    if (latLngs.length) {
        boundaryLine = L.polygon(latLngs, {
            color: '#ffd700',
            weight: 3,
            fillColor: '#34a853',
            fillOpacity: 0.18
        }).addTo(mapEditor);
        mapEditor.fitBounds(boundaryLine.getBounds(), {padding: [35, 35], maxZoom: 21});
    }

    boundaryPoints.forEach((point, index) => {
        const marker = L.marker([point.latitude, point.longitude], {
            draggable: false,
            bubblingMouseEvents: false,
            riseOnHover: true,
            zIndexOffset: 1000,
            icon: pointIcon(selectedPointIndex === index)
        }).addTo(mapEditor);
        marker.on('click', () => selectPoint(index, false));
        const markerElement = marker.getElement();
        if (markerElement) {
            L.DomEvent.disableClickPropagation(markerElement);
            L.DomEvent.disableScrollPropagation(markerElement);
            L.DomEvent.on(markerElement, 'mousedown', event => startManualPointDrag(event, index));
        }
        boundaryMarkers.push(marker);
    });
    renderPointList();
}

function startManualPointDrag(event, index) {
    L.DomEvent.stop(event);
    manualPointDragIndex = index;
    selectPoint(index, false);
    if (mapEditor && mapEditor.dragging) {
        mapEditor.dragging.disable();
    }
    handleManualPointDrag(event);
}

function handleManualPointDrag(event) {
    if (manualPointDragIndex === null || !mapEditor) return;
    const latLng = mapEditor.mouseEventToLatLng(event);
    boundaryPoints[manualPointDragIndex] = {
        latitude: latLng.lat,
        longitude: latLng.lng
    };
    const marker = boundaryMarkers[manualPointDragIndex];
    if (marker) {
        marker.setLatLng(latLng);
    }
    updateBoundaryLine();
    renderPointList();
}

function finishManualPointDrag() {
    if (manualPointDragIndex === null) return;
    const finishedIndex = manualPointDragIndex;
    manualPointDragIndex = null;
    if (mapEditor && mapEditor.dragging) {
        mapEditor.dragging.enable();
    }
    selectPoint(finishedIndex, false);
    setMapEditorStatus(`${activeMapName}: Punkt verschoben, noch nicht gespeichert`);
}

function updateBoundaryLine() {
    if (!boundaryLine) return;
    boundaryLine.setLatLngs([boundaryPoints.map(point => [point.latitude, point.longitude])]);
}

function renderPointList() {
    const list = document.getElementById('pointList');
    if (!boundaryPoints.length) {
        list.textContent = 'Keine Punkte';
        return;
    }
    list.innerHTML = '';
    boundaryPoints.forEach((point, index) => {
        const item = document.createElement('div');
        item.className = 'point-item' + (selectedPointIndex === index ? ' active' : '');
        item.onclick = () => selectPoint(index, true);
        item.innerHTML = `<span>${index + 1}</span><span>${point.latitude.toFixed(7)}, ${point.longitude.toFixed(7)}</span>`;
        list.appendChild(item);
    });
}

function selectPoint(index, panToPoint = false) {
    selectedPointIndex = index;
    boundaryMarkers.forEach((marker, markerIndex) => {
        marker.setIcon(pointIcon(markerIndex === index));
    });
    renderPointList();
    const point = boundaryPoints[index];
    if (panToPoint && point && mapEditor) {
        mapEditor.panTo([point.latitude, point.longitude]);
    }
}

function deleteSelectedPoint() {
    if (selectedPointIndex === null || selectedPointIndex < 0) {
        setMapEditorStatus('Kein Punkt ausgewählt');
        return;
    }
    if (boundaryPoints.length <= 3) {
        setMapEditorStatus('Mindestens drei Punkte müssen bleiben');
        return;
    }
    boundaryPoints.splice(selectedPointIndex, 1);
    selectedPointIndex = null;
    renderBoundaryEditor();
    setMapEditorStatus(`${activeMapName}: Punkt gelöscht, noch nicht gespeichert`);
}

function saveEditedMap() {
    if (!activeMapName) {
        setMapEditorStatus('Keine Karte geladen');
        return;
    }
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/boundary`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({points: boundaryPoints})
    })
    .then(response => response.json().then(data => ({ok: response.ok, data})))
    .then(result => {
        if (!result.ok || result.data.success === false) {
            setMapEditorStatus(result.data.error || 'Speichern fehlgeschlagen');
            return;
        }
        activeMapPayload = result.data.map;
        boundaryPoints = boundaryPointsFromGeoJSON(activeMapPayload);
        renderBoundaryEditor();
        setMapEditorStatus(`${activeMapName}: gespeichert`);
        loadMapAnalysis(activeMapName);
    });
}

function renameSelectedMap() {
    const oldName = activeMapName || document.getElementById('mapSelect').value;
    if (!oldName) {
        setMapEditorStatus('Keine Karte gewählt');
        return;
    }
    const newName = prompt('Neuer Kartenname', oldName);
    if (!newName) return;
    fetch(`/api/mapping/maps/${encodeURIComponent(oldName)}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: newName})
    })
    .then(response => response.json().then(data => ({ok: response.ok, data})))
    .then(result => {
        if (!result.ok || result.data.success === false) {
            setMapEditorStatus(result.data.error || 'Umbenennen fehlgeschlagen');
            return;
        }
        activeMapName = result.data.name;
        activeMapPayload = result.data.map;
        refreshMapList().then(() => {
            document.getElementById('mapSelect').value = activeMapName;
            loadMap(activeMapName);
        });
    });
}

function deleteSelectedMap() {
    const name = activeMapName || document.getElementById('mapSelect').value;
    if (!name) {
        setMapEditorStatus('Keine Karte gewählt');
        return;
    }
    if (!confirm(`${name} löschen?`)) return;
    fetch(`/api/mapping/maps/${encodeURIComponent(name)}`, {method: 'DELETE'})
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            if (!result.ok || result.data.success === false) {
                setMapEditorStatus(result.data.error || 'Löschen fehlgeschlagen');
                return;
            }
            clearMapEditor();
            refreshMapList();
        });
}

function clearMapEditor() {
    activeMapName = '';
    activeMapPayload = null;
    boundaryPoints = [];
    selectedPointIndex = null;
    boundaryMarkers.forEach(marker => marker.remove());
    boundaryMarkers = [];
    subMapLayers.forEach(layer => layer.remove());
    subMapLayers = [];
    clearLanePreview();
    refreshPlanList();
    if (boundaryLine) boundaryLine.remove();
    boundaryLine = null;
    renderPointList();
    clearMapAnalysis();
    setMapEditorStatus('Keine Karte geladen');
}

function setMapEditorStatus(message) {
    document.getElementById('mapEditorStatus').textContent = message;
}

// Lane planner request and preview rendering
function plannerNumber(id) {
    return Number(document.getElementById(id).value || 0);
}

function generateLanePreview() {
    if (!activeMapName) {
        setPlannerStatus('Keine Hauptkarte geladen');
        return;
    }
    const params = new URLSearchParams({
        cut_width_m: plannerNumber('plannerCutWidth'),
        overlap_m: plannerNumber('plannerOverlap'),
        outer_margin_m: plannerNumber('plannerOuterMargin'),
        sub_margin_m: plannerNumber('plannerSubMargin'),
        max_ring_turn_deg: plannerNumber('plannerMaxRingTurn'),
        sub_contour_count: plannerNumber('plannerSubContourCount'),
        rest_pattern: document.getElementById('plannerRestPattern')?.value || 'parallel'
    });
    setPlannerStatus('Bahnen werden berechnet...');
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan?${params}`)
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            if (!result.ok || result.data.success === false) {
                clearLanePreview(false);
                setPlannerStatus(result.data.error || 'Bahnenplanung fehlgeschlagen');
                return;
            }
            renderLanePreview(result.data, 'preview');
            setLoadedPlanReady(false);
            refreshPlanButtons();
            const planWarnings = result.data.warnings || [];
            if (planWarnings.length) {
                setPlannerStatus(`⚠️ ${planWarnings.join(' · ')}`);
            }
        })
        .catch(error => {
            clearLanePreview(false);
            setPlannerStatus(error.message);
        });
}

function renderLanePreview(plan, source = 'preview') {
    clearLanePreview(false);
    setSimulationStatus('Noch nicht simuliert');
    lanePreviewPlan = plan;
    lanePreviewSource = source;
    setLoadedPlanReady(false);
    const lanes = plan.lanes || [];
    lanes.forEach(lane => {
        const latLngs = (lane.coordinates || []).map(coord => [coord[1], coord[0]]);
        if (latLngs.length < 2) return;
        const subContour = lane.type === 'sub_contour';
        const layer = L.polyline(latLngs, {
            color: subContour ? '#ffcf5a' : '#ffe66d',
            weight: subContour ? 3 : 2,
            opacity: 0.95,
            dashArray: subContour ? '10 4' : null,
        }).addTo(mapEditor);
        const label = subContour ? 'Sub-Kontur' : 'Ring';
        layer.bindTooltip(`${label} ${lane.lane_index + 1}: ${lane.length_m} m`);
        lanePreviewLayers.push(layer);
        lanePreviewLaneLayers[lane.lane_index || 0] = layer;
    });
    (plan.rest_lanes || []).forEach(restLane => {
        const latLngs = (restLane.coordinates || []).map(coord => [coord[1], coord[0]]);
        if (latLngs.length < 2) return;
        const reverse = restLane.direction === 'reverse';
        const layer = L.polyline(latLngs, {
            color: reverse ? '#7fdcff' : '#9fffe0',
            weight: 3,
            opacity: 0.95,
            dashArray: reverse ? '8 6' : null,
        }).addTo(mapEditor);
        layer.bindTooltip(`Restbahn ${restLane.rest_index + 1} · ${reverse ? 'rückwärts' : 'vorwärts'} · ${restLane.length_m} m`);
        lanePreviewLayers.push(layer);
        lanePreviewRestLayers[restLane.rest_index || 0] = layer;
    });
    (plan.sequence || []).filter(segment => segment.type === 'connector').forEach(connector => {
        const latLngs = (connector.coordinates || []).map(coord => [coord[1], coord[0]]);
        if (latLngs.length < 2) return;
        const layer = L.polyline(latLngs, {
            color: '#e8f7ff',
            weight: 4,
            opacity: 0.95,
            dashArray: '10 7'
        }).addTo(mapEditor);
        layer.bindTooltip(`Übergang ${connector.from_lane_index + 1} → ${connector.to_lane_index + 1}: ${connector.length_m} m`);
        lanePreviewLayers.push(layer);
        lanePreviewConnectorLayers[connector.segment_index || 0] = layer;
    });
    (plan.transitions || []).forEach(transition => {
        const latLngs = (transition.coordinates || []).map(coord => [coord[1], coord[0]]);
        if (latLngs.length < 2 || transition.length_m < 0.05) return;
        const safe = transition.safe === true;
        const reason = safe ? 'ok' : (transition.reason === 'sub_zone' ? 'Sub-Zone' : 'außerhalb Mähfläche');
        if (safe) {
            const routed = transition.route_kind === 'around_sub';
            const layer = L.polyline(latLngs, {
                color: routed ? '#ffffff' : '#ffffff',
                weight: routed ? 4 : 3,
                opacity: routed ? 0.9 : 0.65,
                dashArray: routed ? '12 5' : '6 8',
            }).addTo(mapEditor);
            const label = routed ? 'geroutet um Sub' : 'ok';
            layer.bindTooltip(`Übergang ${transition.transition_index + 1} · ${label} · ${transition.length_m} m`);
            lanePreviewLayers.push(layer);
            return;
        }
        latLngs.forEach((latLng, endpointIndex) => {
            const marker = L.circleMarker(latLng, {
                radius: 6,
                color: '#ff2f7d',
                weight: 3,
                fillColor: endpointIndex === 0 ? '#ff2f7d' : '#ffffff',
                fillOpacity: 0.9,
            }).addTo(mapEditor);
            marker.bindTooltip(`Unsicherer Sequenzsprung ${transition.transition_index + 1} · ${reason} · ${transition.length_m} m`);
            lanePreviewLayers.push(marker);
        });
    });
    (plan.exclusion_contours || []).forEach(contour => {
        const latLngs = (contour.coordinates || []).map(coord => [coord[1], coord[0]]);
        if (latLngs.length < 2) return;
        const layer = L.polyline(latLngs, {
            color: '#ff8a4a',
            weight: 3,
            opacity: 0.95,
            dashArray: '4 6'
        }).addTo(mapEditor);
        layer.bindTooltip(`Sub-Pufferkontur: ${contour.length_m} m`);
        lanePreviewLayers.push(layer);
    });
    updateLaneProgress(0);
    const unsafe = plan.unsafe_transition_count || 0;
    const transitionText = unsafe > 0
        ? `${unsafe} unsichere Übergänge`
        : `${plan.transition_count || 0} geprüfte Übergänge ok`;
    const subContours = (plan.sequence || []).filter(segment => segment.type === 'sub_contour').length;
    setPlannerStatus(`${plan.lane_count} Ringe · ${subContours} Sub-Konturen · ${plan.rest_lane_count || 0} Restbahnen · ${transitionText} · ${formatArea(plan.mow_length_m || 0)} m Ringfahrt · ${formatArea(plan.rest_length_m || 0)} m Restfläche`);
    setPlanStatus(planSummaryText(plan));
    updateActivePlanLabel();
    refreshPlanButtons();
}

function clearLanePreview(resetStatus = true) {
    clearLaneSimulation(false);
    lanePreviewLayers.forEach(layer => layer.remove());
    lanePreviewLayers = [];
    lanePreviewLaneLayers = [];
    lanePreviewRestLayers = [];
    lanePreviewConnectorLayers = [];
    lanePreviewPlan = null;
    lanePreviewSource = 'none';
    setLoadedPlanReady(false);
    if (laneProgressMarker) {
        laneProgressMarker.remove();
        laneProgressMarker = null;
    }
    const slider = document.getElementById('laneProgressSlider');
    if (slider) slider.value = 0;
    const value = document.getElementById('laneProgressValue');
    if (value) value.textContent = '0,0%';
    const detail = document.getElementById('laneProgressDetail');
    if (detail) detail.textContent = '0 m / 0 m';
    if (resetStatus) {
        setPlannerStatus('Kein Plan geladen');
        setPlanStatus('Kein Plan geladen');
        setSimulationStatus('Noch nicht simuliert');
    }
    updateActivePlanLabel();
    refreshPlanButtons();
}

function simulateLanePlan() {
    if (laneSimulationRunning) return;
    if (!activeMapName || !lanePreviewPlan) {
        setSimulationStatus('Kein Plan für Simulation geladen');
        return;
    }
    const start = selectedPlanStart();
    if (!start) {
        setSimulationStatus('Keine gültige Simulations-Startposition');
        return;
    }
    const useCurrentPose = document.getElementById('simulationUseCurrentPose')?.checked === true;
    // Die Simulation rechnet nur - sie bewegt nichts. Deshalb verlangt sie
    // eine Position, aber keinen RTK-Fix: sonst laesst sich eine Anfahrt
    // ausgerechnet dann nicht durchrechnen, wenn das Fahrzeug wegen fehlendem
    // Fix ohnehin steht. Losfahren bleibt an RTK FIXED gebunden, das
    // entscheidet planReadiness weiter unten.
    if (useCurrentPose && latestVehiclePose === null) {
        setSimulationStatus('Für die simulierte Anfahrt fehlt die Fahrzeugposition');
        return;
    }
    laneSimulationRunning = true;
    clearLaneSimulation(false);
    laneSimulationRunning = true;
    laneSimulationAbortController = new AbortController();
    refreshPlanButtons();
    const startLabel = useCurrentPose
        ? (rtkAvailable
            ? 'ab aktueller RTK-Position'
            : 'ab aktueller Position OHNE RTK-Fix – die Lage kann Meter danebenliegen')
        : 'ab gewählter Abfahrposition';
    const scopeValue = document.getElementById('simulationScope')?.value || '3';
    const maxSourceSegments = scopeValue === 'all' ? null : Number(scopeValue);
    const scopeLabel = maxSourceSegments === null
        ? 'gesamter Restplan'
        : `nächste ${maxSourceSegments} Plansegmente`;
    setSimulationStatus(`Reglersimulation wird berechnet · ${startLabel} · ${scopeLabel}`);
    const requestPayload = {
        start_segment_index: start.segmentIndex,
        start_coordinate: start.coordinate,
        use_current_pose: useCurrentPose,
        parameters: {
            step_s: 0.1,
            sample_distance_m: 0.15,
            sample_interval_s: 0.2,
            max_steps: 120000,
        },
    };
    if (maxSourceSegments !== null) requestPayload.max_source_segments = maxSourceSegments;
    if (lanePreviewSource !== 'saved') requestPayload.plan = lanePreviewPlan;
    laneSimulationTimer = window.setInterval(pollLaneSimulationStatus, 750);
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/simulate`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestPayload),
        signal: laneSimulationAbortController.signal,
    })
        .then(parseJsonResponse)
        .then(result => {
            if (!result.ok || !result.data.success) {
                setSimulationStatus(result.data.reason || result.data.error || 'Simulation fehlgeschlagen');
                laneSimulationRunning = false;
                return;
            }
            renderLaneSimulation(result.data);
        })
        .catch(error => {
            if (error.name === 'AbortError') return;
            laneSimulationRunning = false;
            setSimulationStatus(error.message);
        })
        .finally(() => {
            if (laneSimulationTimer !== null) {
                window.clearInterval(laneSimulationTimer);
                laneSimulationTimer = null;
            }
            refreshPlanButtons();
        });
}

function pollLaneSimulationStatus() {
    if (!laneSimulationRunning || laneSimulationPlayback || !activeMapName) return;
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/simulate/status`)
        .then(parseJsonResponse)
        .then(result => {
            if (!laneSimulationRunning || laneSimulationPlayback || !result.ok) return;
            const status = result.data || {};
            if (status.phase === 'route_building') {
                setSimulationStatus(
                    `Ausführbare Route wird erstellt · ${Number(status.wall_time_s || 0).toFixed(1).replace('.', ',')} s`
                );
                return;
            }
            if (status.phase === 'simulating') {
                const current = Number(status.executable_index || 0) + 1;
                const total = Number(status.executable_segment_count || 0);
                setSimulationStatus(
                    `Reglersimulation wird berechnet · Abschnitt ${current}/${total || '?'} · ` +
                    `${formatArea(status.actual_length_m || 0)} m · simulierte Zeit ` +
                    `${Number(status.elapsed_s || 0).toFixed(1).replace('.', ',')} s`
                );
            }
        })
        .catch(() => {});
}

function renderLaneSimulation(result) {
    clearLaneSimulation(false, false);
    const samples = (result.trajectory || []).filter(item => (
        Number.isFinite(Number(item.longitude))
        && Number.isFinite(Number(item.latitude))
        && Number.isFinite(Number(item.time_s))
    ));
    laneSimulationResult = result;
    laneSimulationPlayback = {
        samples,
        currentTimeS: 0,
        totalTimeS: samples.length ? Number(samples[samples.length - 1].time_s) : 0,
        sampleIndex: 0,
        lastTimestamp: null,
        vehicleLengthM: Number(result.parameters?.vehicle_length_m || 1.15),
        vehicleWidthM: Number(result.parameters?.vehicle_width_m || 0.79),
    };
    if (!samples.length) {
        laneSimulationRunning = false;
        setSimulationStatus(result.reason || 'Die Reglersimulation enthält keine Fahrzeugbewegung');
        refreshPlanButtons();
        return;
    }
    drawLaneSimulationTrajectory(samples);
    laneSimulationPaused = false;
    laneSimulationRunning = true;
    updateLaneSimulationPose(0);
    laneSimulationAnimationFrame = window.requestAnimationFrame(animateLaneSimulation);
    refreshPlanButtons();
}

function drawLaneSimulationTrajectory(samples) {
    const groups = [];
    samples.forEach(sample => {
        let group = groups[groups.length - 1];
        if (!group || group.executableIndex !== sample.executable_index) {
            group = {
                executableIndex: sample.executable_index,
                type: sample.type,
                direction: sample.direction,
                coordinates: [],
            };
            groups.push(group);
        }
        group.coordinates.push([Number(sample.latitude), Number(sample.longitude)]);
    });
    groups.forEach(group => {
        if (group.coordinates.length < 2) return;
        const isTransfer = group.type === 'transition' || group.type === 'positioning';
        const reverse = group.direction === 'reverse';
        const color = isTransfer ? '#ff5a00' : (reverse ? '#25c6ff' : '#ff00ff');
        const layer = L.polyline(group.coordinates, {
            color,
            weight: isTransfer ? 8 : 5,
            opacity: 0.90,
            dashArray: isTransfer ? '10 5' : (reverse ? '8 5' : null),
        }).addTo(mapEditor);
        const type = isTransfer
            ? `Anfahrt/Übergang ${reverse ? 'rückwärts' : 'vorwärts'}`
            : (reverse ? 'Rückwärts' : 'Vorwärts');
        layer.bindTooltip(`Berechnete Fahrzeugspur · ${type} · Abschnitt ${Number(group.executableIndex) + 1}`);
        laneSimulationLayers.push(layer);
    });
}

function appendLaneSimulationSegments(executableSegments) {
    const playback = laneSimulationPlayback;
    if (!playback) return;
    const executableOffset = Number(laneSimulationResult?.executable_segment_count || 0);
    executableSegments.forEach((segment, chunkIndex) => {
        const executableIndex = executableOffset + chunkIndex;
        const coords = segment.coordinates || [];
        if (coords.length < 2) return;
        const isTransfer = segment.type === 'transition' || segment.type === 'positioning';
        const isTransition = segment.type === 'transition';
        const isReverse = segment.direction === 'reverse';
        const color = isTransfer ? '#ff5a00' : (isReverse ? '#25c6ff' : '#ff00ff');
        const layer = L.polyline(coords.map(coord => [coord[1], coord[0]]), {
            color,
            weight: isTransfer ? 8 : 4,
            opacity: isTransfer ? 1.0 : 0.72,
            dashArray: isTransfer ? '10 5' : (isReverse ? '8 5' : null),
        }).addTo(mapEditor);
        const type = isTransfer
            ? `Übergang/Anfahrt ${isReverse ? 'rückwärts' : 'vorwärts'}`
            : (isReverse ? 'Rückwärts' : 'Vorwärts');
        layer.bindTooltip(`Ausführbare Route · ${type} · Abschnitt ${executableIndex + 1}`);
        laneSimulationLayers.push(layer);
        if (isTransition) {
            const markerCoord = coords[Math.floor(coords.length / 2)];
            const marker = L.circleMarker([markerCoord[1], markerCoord[0]], {
                radius: 6,
                color: '#ffffff',
                weight: 2,
                fillColor: '#ff5a00',
                fillOpacity: 1.0,
            }).addTo(mapEditor);
            marker.bindTooltip(`Übergang · Abschnitt ${executableIndex + 1}`);
            laneSimulationLayers.push(marker);
        }
        for (let index = 0; index < coords.length - 1; index += 1) {
            const lengthM = distanceLatLngM(coords[index], coords[index + 1]);
            if (lengthM <= 0.001) continue;
            playback.legs.push({
                a: coords[index],
                b: coords[index + 1],
                startM: playback.totalLengthM,
                endM: playback.totalLengthM + lengthM,
                lengthM,
                segment,
                executableIndex,
            });
            playback.totalLengthM += lengthM;
        }
    });
}

function clearLaneSimulation(resetStatus = true, abortRequest = true) {
    if (laneSimulationAnimationFrame !== null) {
        window.cancelAnimationFrame(laneSimulationAnimationFrame);
        laneSimulationAnimationFrame = null;
    }
    if (laneSimulationTimer !== null) {
        window.clearInterval(laneSimulationTimer);
        laneSimulationTimer = null;
    }
    if (abortRequest && laneSimulationAbortController !== null) {
        laneSimulationAbortController.abort();
    }
    laneSimulationAbortController = null;
    laneSimulationLayers.forEach(layer => layer.remove());
    laneSimulationLayers = [];
    laneSimulationResult = null;
    laneSimulationPlayback = null;
    laneSimulationMarker = null;
    laneSimulationFootprint = null;
    laneSimulationPaused = false;
    laneSimulationRunning = false;
    if (resetStatus) setSimulationStatus('Noch nicht simuliert');
}

function invalidateLaneSimulationSelection() {
    // A simulation belongs to one exact slider position and start mode. Do
    // not leave Play visually armed after either input changes.
    clearLaneSimulation(true);
    refreshPlanButtons();
}

function animateLaneSimulation(timestamp) {
    if (!laneSimulationRunning || !laneSimulationPlayback) return;
    if (laneSimulationPaused) {
        laneSimulationPlayback.lastTimestamp = timestamp;
        laneSimulationAnimationFrame = window.requestAnimationFrame(animateLaneSimulation);
        return;
    }
    if (laneSimulationPlayback.lastTimestamp === null) {
        laneSimulationPlayback.lastTimestamp = timestamp;
    }
    const elapsedS = Math.max(0, Math.min(0.25, (timestamp - laneSimulationPlayback.lastTimestamp) / 1000));
    laneSimulationPlayback.lastTimestamp = timestamp;
    const speedFactor = Number(document.getElementById('simulationSpeed')?.value || 10);
    laneSimulationPlayback.currentTimeS = Math.min(
        laneSimulationPlayback.totalTimeS,
        laneSimulationPlayback.currentTimeS + elapsedS * speedFactor
    );
    updateLaneSimulationPose(laneSimulationPlayback.currentTimeS);
    if (laneSimulationPlayback.currentTimeS >= laneSimulationPlayback.totalTimeS) {
        laneSimulationRunning = false;
        laneSimulationAnimationFrame = null;
        laneSimulationAbortController = null;
        if (laneSimulationResult.safe !== true) {
            setSimulationStatus(
                `Reglersimulation STOP · ${laneSimulationResult.reason || laneSimulationResult.state || 'unbekannter Grund'} · ` +
                `${formatArea(laneSimulationResult.actual_length_m || 0)} m gefahren`
            );
            refreshPlanButtons();
            return;
        }
        setSimulationStatus(
            `Reglersimulation abgeschlossen · ${formatArea(laneSimulationResult.actual_length_m || 0)} m · ` +
            `${laneSimulationResult.executable_segment_count || 0} ausführbare Abschnitte · ` +
            `${laneSimulationResult.source_segment_limit ? `${laneSimulationResult.source_segment_limit} Plansegmente` : 'gesamter Restplan'}`
        );
        refreshPlanButtons();
        return;
    }
    laneSimulationAnimationFrame = window.requestAnimationFrame(animateLaneSimulation);
}

function requestNextLaneSimulationChunk() {
    const playback = laneSimulationPlayback;
    if (!playback || !playback.hasMore || playback.loadingMore || !laneSimulationRunning) return;
    const lastLeg = playback.legs[playback.legs.length - 1];
    if (!lastLeg || playback.nextSegmentIndex === null || playback.nextSegmentIndex === undefined) return;
    playback.loadingMore = true;
    const requestPayload = {
        start_segment_index: playback.nextSegmentIndex,
        continuation_pose: {longitude: lastLeg.b[0], latitude: lastLeg.b[1]},
        max_source_segments: 2,
    };
    if (lanePreviewSource !== 'saved') requestPayload.plan = lanePreviewPlan;
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/playback`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestPayload),
        signal: laneSimulationAbortController?.signal,
    })
        .then(parseJsonResponse)
        .then(result => {
            if (!laneSimulationRunning || !laneSimulationPlayback) return;
            if (!result.ok || !result.data.success) {
                throw new Error(result.data.error || 'Nächster Routenabschnitt konnte nicht erstellt werden');
            }
            appendLaneSimulationSegments(result.data.executable_segments || []);
            laneSimulationResult.executable_segment_count += Number(result.data.executable_segment_count || 0);
            playback.hasMore = result.data.has_more === true;
            playback.nextSegmentIndex = result.data.next_source_segment_index;
            playback.chunksLoaded += 1;
            playback.loadingMore = false;
            requestNextLaneSimulationChunk();
        })
        .catch(error => {
            if (error.name === 'AbortError') return;
            playback.loadingMore = false;
            playback.hasMore = false;
            playback.terminalError = error.message;
        });
}

function updateLaneSimulationPose(simulationTimeS) {
    const playback = laneSimulationPlayback;
    if (!playback) return;
    const samples = playback.samples;
    while (
        playback.sampleIndex < samples.length - 2
        && Number(samples[playback.sampleIndex + 1].time_s) < simulationTimeS
    ) {
        playback.sampleIndex += 1;
    }
    while (
        playback.sampleIndex > 0
        && Number(samples[playback.sampleIndex].time_s) > simulationTimeS
    ) {
        playback.sampleIndex -= 1;
    }
    const a = samples[playback.sampleIndex];
    const b = samples[Math.min(samples.length - 1, playback.sampleIndex + 1)];
    const spanS = Math.max(0.001, Number(b.time_s) - Number(a.time_s));
    const fraction = Math.max(0, Math.min(1, (simulationTimeS - Number(a.time_s)) / spanS));
    const longitude = Number(a.longitude) + (Number(b.longitude) - Number(a.longitude)) * fraction;
    const latitude = Number(a.latitude) + (Number(b.latitude) - Number(a.latitude)) * fraction;
    const headingDelta = ((Number(b.heading_deg) - Number(a.heading_deg) + 540) % 360) - 180;
    const heading = (Number(a.heading_deg) + headingDelta * fraction + 360) % 360;
    const latLng = [latitude, longitude];
    if (!laneSimulationMarker) {
        laneSimulationMarker = L.marker(latLng, {
            icon: vehicleIcon(heading),
            zIndexOffset: 3000,
            interactive: false,
        }).addTo(mapEditor);
        laneSimulationLayers.push(laneSimulationMarker);
    } else {
        laneSimulationMarker.setLatLng(latLng);
        laneSimulationMarker.setIcon(vehicleIcon(heading));
    }
    const footprint = footprintLatLngs(latitude, longitude, heading, playback.vehicleLengthM, playback.vehicleWidthM);
    if (!laneSimulationFootprint) {
        laneSimulationFootprint = L.polygon(footprint, {
            color: '#00ff9d',
            weight: 3,
            fillColor: '#00ff9d',
            fillOpacity: 0.20,
            // Die Fahrzeugkontur ist 1,15 x 0,79 m gross und deckt beim
            // Abspielen ganze Kartenpunkte zu. Ohne das hier fängt sie deren
            // Klicks ab und der Punkt lässt sich nicht mehr anfassen.
            interactive: false,
        }).addTo(mapEditor);
        laneSimulationLayers.push(laneSimulationFootprint);
    } else {
        laneSimulationFootprint.setLatLngs(footprint);
    }
    const sample = fraction < 0.5 ? a : b;
    const isTransfer = sample.type === 'transition' || sample.type === 'positioning';
    const reverse = sample.direction === 'reverse';
    const type = isTransfer
        ? `Anfahrt/Übergang ${reverse ? 'rückwärts' : 'vorwärts'}`
        : (reverse ? 'Rückwärts' : 'Vorwärts');
    const progress = playback.totalTimeS > 0 ? simulationTimeS / playback.totalTimeS * 100 : 100;
    const commandX = Number(sample.command_x || 0).toFixed(2).replace('.', ',');
    const commandY = Number(sample.command_y || 0).toFixed(2).replace('.', ',');
    setSimulationStatus(
        `${laneSimulationPaused ? 'Reglersimulation pausiert' : 'Reglersimulation läuft'} · ` +
        `${progress.toFixed(1).replace('.', ',')}% · t=${simulationTimeS.toFixed(1).replace('.', ',')} s · ` +
        `${type} · Abschnitt ${Number(sample.executable_index) + 1} · Regler x=${commandX} y=${commandY}`
    );
}

function toggleLaneSimulationPause() {
    if (!laneSimulationRunning || !laneSimulationPlayback) return;
    laneSimulationPaused = !laneSimulationPaused;
    laneSimulationPlayback.lastTimestamp = null;
    updateLaneSimulationPose(laneSimulationPlayback.currentTimeS);
    refreshPlanButtons();
}

function stopLaneSimulation() {
    if (activeMapName) {
        fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/simulate/cancel`, {
            method: 'POST',
            keepalive: true,
        }).catch(() => {});
    }
    clearLaneSimulation(false);
    setSimulationStatus('Simulation abgebrochen');
    refreshPlanButtons();
}

function bearingDegrees(a, b) {
    const latitude = (a[1] + b[1]) / 2 * Math.PI / 180;
    const east = (b[0] - a[0]) * Math.cos(latitude);
    const north = b[1] - a[1];
    return (Math.atan2(east, north) * 180 / Math.PI + 360) % 360;
}

function footprintLatLngs(latitude, longitude, headingDeg, lengthM, widthM) {
    const heading = headingDeg * Math.PI / 180;
    const frontEast = Math.sin(heading);
    const frontNorth = Math.cos(heading);
    const rightEast = Math.cos(heading);
    const rightNorth = -Math.sin(heading);
    const halfLength = lengthM / 2;
    const halfWidth = widthM / 2;
    return [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([front, right]) => {
        const eastM = front * halfLength * frontEast + right * halfWidth * rightEast;
        const northM = front * halfLength * frontNorth + right * halfWidth * rightNorth;
        const lat = latitude + northM / 6371000 * 180 / Math.PI;
        const lon = longitude + eastM / (6371000 * Math.max(0.01, Math.cos(latitude * Math.PI / 180))) * 180 / Math.PI;
        return [lat, lon];
    });
}

function setSimulationStatus(message) {
    const el = document.getElementById('planSimulationStatus');
    if (el) el.textContent = message;
}

function parseJsonResponse(response) {
    return response.json().then(data => ({ok: response.ok, data}));
}

function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds || 0)));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return minutes > 0 ? `${minutes} min ${rest} s` : `${rest} s`;
}

function saveLanePlan() {
    if (!activeMapName || !lanePreviewPlan) {
        setPlannerStatus('Kein berechneter Plan zum Speichern');
        return;
    }
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/save`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({plan: lanePreviewPlan})
    })
        .then(parseJsonResponse)
        .then(result => {
            if (!result.ok || !result.data.success) {
                setPlannerStatus(result.data.error || 'Plan speichern fehlgeschlagen');
                return;
            }
            setLoadedPlanReady(true);
            lanePreviewSource = 'saved';
            updateActivePlanLabel();
            setPlannerStatus(`Plan gespeichert · ${planSummaryText(result.data.summary || result.data.plan || lanePreviewPlan)}`);
            refreshPlanList().then(() => {
                const select = document.getElementById('planSelect');
                if (select) select.value = activeMapName;
            });
            refreshPlanButtons();
        })
        .catch(error => setPlannerStatus(error.message));
}

function refreshPlanList() {
    return fetch('/api/mapping/plans')
        .then(response => response.json())
        .then(data => {
            savedPlans = data.plans || [];
            if (!planIsRunning && activeMapName) {
                planResumeAvailable = savedPlanHasResume(activeMapName);
            }
            const select = document.getElementById('planSelect');
            if (!select) return savedPlans;
            const current = select.value || activeMapName;
            select.innerHTML = '<option value="">Kein gespeicherter Plan</option>';
            savedPlans.forEach(plan => {
                const option = document.createElement('option');
                option.value = plan.map_name;
                option.textContent = `${plan.map_name} · ${formatArea(plan.total_drive_length_m)} m`;
                select.appendChild(option);
            });
            if (current && savedPlans.some(plan => plan.map_name === current)) {
                select.value = current;
            }
            refreshPlanButtons();
            return savedPlans;
        })
        .catch(() => savedPlans);
}

function savedPlanHasResume(mapName) {
    return Boolean(mapName) && savedPlans.some(
        plan => plan.map_name === mapName && plan.resume_available === true
    );
}

function selectSavedPlan() {
    const selected = document.getElementById('planSelect')?.value;
    if (!selected) return;
    loadSavedPlan();
}

// Der Name ist optional: ohne ihn gilt die Auswahlliste, wie beim Klick auf
// "Plan laden". Die Rueckmeldung sagt, ob der Plan wirklich im Browser steht -
// daran haengt, ob das Nachladen eines laufenden Plans als erledigt gilt.
function loadSavedPlan(requestedMapName) {
    if (planLoadRunning) return Promise.resolve(false);
    const requested = typeof requestedMapName === 'string' ? requestedMapName : '';
    const mapName = requested || document.getElementById('planSelect')?.value || activeMapName;
    if (!mapName) {
        setPlanStatus('Keine Karte oder kein Plan gewählt');
        return Promise.resolve(false);
    }
    planLoadRunning = true;
    refreshPlanButtons();
    setPlanStatus('Plan wird geladen...');
    return fetch(`/api/mapping/maps/${encodeURIComponent(mapName)}/plan/load`)
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            if (!result.ok || result.data.success === false) {
                setPlanStatus(result.data.error || 'Plan laden fehlgeschlagen');
                return false;
            }
            const activateLoadedPlan = () => {
                renderLanePreview(result.data.plan, 'saved');
                setLoadedPlanReady(true);
                planResumeAvailable = savedPlanHasResume(mapName);
                enterPlanUiMode(mapName);
                showPlanInSelect(mapName);
                refreshPlanButtons();
                // Waehrend der Fahrt prueft der Dienst die No-Go-Zonen ohnehin
                // laufend und schickt das Ergebnis im Status mit - eine zweite
                // Pruefung nebenher kostet nur Rechenzeit auf dem Fahrzeug.
                if (!planIsRunning) refreshNoGoCheck(mapName, result.data.plan);
                setPlanStatus(`Plan geladen · ${planSummaryText(result.data.summary || result.data.plan)}`);
                return true;
            };
            if (mapName !== activeMapName) {
                return loadMap(mapName).then(loaded => loaded === false ? false : activateLoadedPlan());
            }
            return activateLoadedPlan();
        })
        .catch(error => {
            setPlanStatus(error.message);
            return false;
        })
        .finally(() => {
            planLoadRunning = false;
            refreshPlanButtons();
        });
}

// Die Auswahlliste muss den geladenen Plan auch dann zeigen, wenn er nicht
// ueber sie gewaehlt wurde - sonst steht dort "Kein gespeicherter Plan",
// waehrend das Fahrzeug ihn abfaehrt.
function showPlanInSelect(mapName) {
    const select = document.getElementById('planSelect');
    if (!select || !mapName) return;
    const known = Array.from(select.options).some(option => option.value === mapName);
    if (known) {
        select.value = mapName;
        return;
    }
    refreshPlanList().then(() => {
        if (Array.from(select.options).some(option => option.value === mapName)) {
            select.value = mapName;
        }
    });
}

function refreshNoGoCheck(mapName, plan) {
    fetch(`/api/mapping/maps/${encodeURIComponent(mapName)}/plan/nogo-check`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({plan})
    })
    .then(response => response.json().then(data => ({ok: response.ok, data})))
    .then(result => {
        if (result.ok && result.data.nogo_status) {
            updateNoGoStatus(result.data.nogo_status);
        }
    })
    .catch(() => {});
}

function playLoadedPlan() {
    if (!activeMapName || !lanePreviewPlan) {
        setPlanStatus('Kein Plan geladen');
        return;
    }
    const start = selectedPlanStart();
    if (!start) {
        setPlanStatus('Keine gültige Abfahrposition gewählt');
        return;
    }
    const percentText = start.percent.toFixed(1).replace('.', ',');
    const simulationNote = laneSimulationRunning ? ' Die laufende Simulation wird dafür beendet.' : '';
    if (!confirm(`Plan ab ${percentText}% starten? Das Fahrzeug fährt zuerst zur pink markierten Position.${simulationNote}`)) {
        return;
    }
    const attemptToken = ++planStartAttemptToken;
    const retryDeadline = Date.now() + 35000;
    const beginPreflight = () => {
        if (attemptToken !== planStartAttemptToken) return;
        planBlockedMessage = null;
        planHeadingWarning = null;
    setPlanStatus(`Planstart ab ${percentText}% wird geprüft`);
        checkAndStartLoadedPlan(false, start.segmentIndex, start.coordinate, attemptToken, retryDeadline);
    };
    if (laneSimulationRunning) {
        setPlanStatus('Laufende Simulation wird für den realen Start beendet');
        cancelLaneSimulationForPlanStart().finally(beginPreflight);
        return;
    }
    beginPreflight();
}

function cancelLaneSimulationForPlanStart() {
    const mapName = activeMapName;
    clearLaneSimulation(false);
    setSimulationStatus('Simulation für realen Planstart beendet');
    if (!mapName) return Promise.resolve();
    return fetch(`/api/mapping/maps/${encodeURIComponent(mapName)}/plan/simulate/cancel`, {
        method: 'POST',
        keepalive: true,
    }).catch(() => {});
}

function resumeLoadedPlan() {
    if (!activeMapName || !planResumeAvailable) {
        setPlanStatus('Kein pausierter Plan zum Fortsetzen vorhanden');
        return;
    }
    if (!confirm('Pausierten Plan an der gespeicherten Stelle fortsetzen?')) return;
    const attemptToken = ++planStartAttemptToken;
    const retryDeadline = Date.now() + 35000;
    planBlockedMessage = null;
    planHeadingWarning = null;
    setPlanStatus('Fortsetzen wird geprüft');
    checkAndStartLoadedPlan(true, null, null, attemptToken, retryDeadline);
}

function isTransientRtkStartFailure(data) {
    const messages = [data?.error, ...(data?.errors || [])].filter(Boolean);
    return messages.some(message =>
        message.includes('RTK/GPS-Pose ist nicht aktuell') ||
        message.includes('Keine aktuelle RTK/GPS-Pose vorhanden')
    );
}

function retryPlanStart(useResume, startSegmentIndex, startCoordinate, attemptToken, retryDeadline) {
    if (attemptToken !== planStartAttemptToken) return;
    const remainingSeconds = Math.max(0, Math.ceil((retryDeadline - Date.now()) / 1000));
    setPlanStatus(`Warte auf frische RTK-Daten · noch ${remainingSeconds} s`);
    setTimeout(
        () => checkAndStartLoadedPlan(useResume, startSegmentIndex, startCoordinate, attemptToken, retryDeadline),
        500
    );
}

function checkAndStartLoadedPlan(useResume, startSegmentIndex, startCoordinate, attemptToken, retryDeadline) {
    if (attemptToken !== planStartAttemptToken) return;
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/check`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            start_segment_index: startSegmentIndex,
            start_coordinate: startCoordinate,
            // Ohne dieses Flag prueft der Server beim Fortsetzen die Route ab
            // Bahn 0 statt ab dem Wiederaufsetzpunkt und lehnt sie wegen einer
            // Stelle ab, die gar nicht gefahren wird.
            resume: useResume === true,
        })
    })
    .then(response => response.json().then(data => ({ok: response.ok, data})))
    .then(result => {
        const errors = result.data.errors || [];
        const warnings = result.data.warnings || [];
        if (!result.ok || result.data.success !== true) {
            if (isTransientRtkStartFailure(result.data) && Date.now() < retryDeadline) {
                retryPlanStart(useResume, startSegmentIndex, startCoordinate, attemptToken, retryDeadline);
                return;
            }
            const detail = [result.data.error, ...errors, ...warnings].filter(Boolean).join(' · ');
            // Festhalten, bis der Benutzer selbst etwas auslöst. Die
            // Statusabfrage überschreibt die Zeile sonst nach zwei Sekunden
            // mit dem Navigationszustand - die Ablehnung war real nicht zu
            // sehen und das Fahrzeug stand scheinbar grundlos (02.08.).
            planBlockedMessage = `⛔ Play blockiert${detail ? ' · ' + detail : ''} · ${planSummaryText(result.data.summary || lanePreviewPlan)}`;
            setPlanStatus(planBlockedMessage);
            // Sofort und nicht erst mit der naechsten Statusabfrage: das hier
            // ist die direkte Antwort auf den Klick des Benutzers.
            planAlertDismissed = null;
            setPlanAlert(planBlockedMessage);
            return;
        }
        if (attemptToken !== planStartAttemptToken) return;
        return fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/execute`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                start_segment_index: startSegmentIndex,
                start_coordinate: startCoordinate,
                resume: useResume,
            })
        })
            .then(response => response.json().then(data => ({ok: response.ok, data})))
            .then(executeResult => {
                if (attemptToken !== planStartAttemptToken) return;
                if (executeResult.ok && executeResult.data.success) {
                    planIsRunning = true;
                    updateMapModeButton();
                    updateMapsSectionTitle();
                    // Warnungen der Freigabe gingen hier bisher verloren - der
                    // Zweig schrieb nur 'Plan gestartet'. Genau das war bei den
                    // Winkelsperren die interessante Information: der Plan
                    // startet, bleibt aber an bekannten Stellen stehen.
                    planHeadingWarning = warnings.length ? `⚠️ ${warnings.join(' · ')}` : null;
                    setPlanStatus(planHeadingWarning
                        ? `Plan gestartet · ${planHeadingWarning}`
                        : 'Plan gestartet');
                    return;
                }
                if (isTransientRtkStartFailure(executeResult.data) && Date.now() < retryDeadline) {
                    retryPlanStart(useResume, startSegmentIndex, startCoordinate, attemptToken, retryDeadline);
                    return;
                }
                setPlanStatus(executeResult.data.error || 'Plan-Ausführung nicht gestartet');
            });
    })
    .catch(error => {
        setPlanStatus(error.message);
    });
}

function pausePlanExecution() {
    if (!activeMapName) return;
    planStartAttemptToken += 1;
    fetch(`/api/mapping/maps/${encodeURIComponent(activeMapName)}/plan/pause`, {method: 'POST'})
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            planIsRunning = false;
            planResumeAvailable = true;
            const savedPlan = savedPlans.find(plan => plan.map_name === activeMapName);
            if (savedPlan) savedPlan.resume_available = true;
            updateMapModeButton();
            updateMapsSectionTitle();
            setPlanStatus(result.ok ? 'Pause gesetzt' : (result.data.error || 'Pause fehlgeschlagen'));
        })
        .catch(error => setPlanStatus(error.message));
}

function stopPlanExecution() {
    planStartAttemptToken += 1;
    planHeadingWarning = null;
    fetch('/api/navigation/stop', {method: 'POST'})
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            planIsRunning = false;
            planResumeAvailable = false;
            const savedPlan = savedPlans.find(plan => plan.map_name === activeMapName);
            if (savedPlan) savedPlan.resume_available = false;
            updateMapModeButton();
            updateMapsSectionTitle();
            setPlanStatus(result.ok ? 'Stop gesendet' : (result.data.error || 'Stop fehlgeschlagen'));
        })
        .catch(error => setPlanStatus(error.message));
}

function enterPlanUiMode(planName) {
    planUiMode = 'plan';
    activePlanName = planName || activeMapName || '';
    document.querySelectorAll('.map-edit-control').forEach(el => el.classList.add('map-mode-hidden'));
    document.getElementById('mapsScreen')?.classList.add('plan-mode');
    document.getElementById('mapsScreen')?.classList.toggle('plan-driving', planIsRunning);
    updateMapModeButton();
    updateMapsSectionTitle();
}

function returnToMapEditMode() {
    if (planIsRunning) {
        setPlanStatus('Kartenmodus erst nach Stop möglich');
        return;
    }
    planUiMode = 'map';
    activePlanName = '';
    document.querySelectorAll('.map-edit-control').forEach(el => el.classList.remove('map-mode-hidden'));
    document.getElementById('mapsScreen')?.classList.remove('plan-mode');
    document.getElementById('mapsScreen')?.classList.remove('plan-driving');
    updateMapModeButton();
    updateMapsSectionTitle();
}

function setLoadedPlanReady(ok) {
    loadedPlanReady = ok === true;
}

function planPlayAvailability() {
    if (planIsRunning) return {ready: false, reason: 'Planfahrt läuft bereits'};
    if (!activeMapName || !lanePreviewPlan) return {ready: false, reason: 'zuerst einen Plan laden'};
    if (!loadedPlanReady) return {ready: false, reason: 'zuerst den gespeicherten Plan laden'};
    if (!rtkAvailable) return {ready: false, reason: 'RTK FIXED ist erforderlich'};
    return {ready: true, reason: 'Plan ist startbereit · Simulation optional'};
}

function refreshPlanButtons() {
    const simulationControls = document.getElementById('planSimulationControls');
    if (simulationControls) simulationControls.hidden = !lanePreviewPlan;
    const loadBtn = document.getElementById('planLoadBtn');
    if (loadBtn) {
        // Waehrend einer Fahrt bestimmt das Fahrzeug, welcher Plan angezeigt
        // wird. Sonst koennte hier ein anderer Plan ueber die laufende Fahrt
        // gelegt werden und die Anzeige liefe wieder auseinander.
        loadBtn.disabled = planLoadRunning || planIsRunning;
        loadBtn.textContent = planLoadRunning ? 'Plan wird geladen…' : 'Plan laden';
        loadBtn.title = planIsRunning ? 'Während der Planfahrt zeigt die Karte den laufenden Plan' : '';
    }
    const planSelect = document.getElementById('planSelect');
    if (planSelect) planSelect.disabled = planLoadRunning || planIsRunning;
    const playBtn = document.getElementById('planPlayBtn');
    const playAvailability = planPlayAvailability();
    if (playBtn) {
        playBtn.disabled = !playAvailability.ready;
        playBtn.title = playAvailability.reason;
    }
    const playStatus = document.getElementById('planPlayStatus');
    if (playStatus) {
        playStatus.textContent = `${playAvailability.ready ? 'Play bereit' : 'Play gesperrt'} · ${playAvailability.reason}`;
        playStatus.style.color = playAvailability.ready ? '#90EE90' : '#ffb3a7';
    }
    const saveBtn = document.getElementById('planSaveBtn');
    if (saveBtn) saveBtn.disabled = !activeMapName || !lanePreviewPlan || loadedPlanReady;
    const pauseBtn = document.getElementById('planPauseBtn');
    if (pauseBtn) pauseBtn.disabled = !planIsRunning;
    const resumeBtn = document.getElementById('planResumeBtn');
    if (resumeBtn) resumeBtn.disabled = planIsRunning || !planResumeAvailable || !rtkAvailable;
    const simulateBtn = document.getElementById('planSimulateBtn');
    if (simulateBtn) {
        simulateBtn.disabled = laneSimulationRunning || planIsRunning || !activeMapName || !lanePreviewPlan;
        simulateBtn.textContent = laneSimulationRunning ? 'Simulation läuft…' : 'Simulation starten';
    }
    const simulationPauseBtn = document.getElementById('planSimulationPauseBtn');
    if (simulationPauseBtn) {
        simulationPauseBtn.disabled = !laneSimulationRunning || !laneSimulationPlayback;
        simulationPauseBtn.textContent = laneSimulationPaused ? 'Fortsetzen' : 'Pause';
    }
    const simulationStopBtn = document.getElementById('planSimulationStopBtn');
    if (simulationStopBtn) simulationStopBtn.disabled = !laneSimulationRunning;
    const slider = document.getElementById('laneProgressSlider');
    if (slider) slider.disabled = laneSimulationRunning || planIsRunning || !lanePreviewPlan;
    const currentPoseCheckbox = document.getElementById('simulationUseCurrentPose');
    if (currentPoseCheckbox) currentPoseCheckbox.disabled = laneSimulationRunning || planIsRunning;
    const simulationSpeed = document.getElementById('simulationSpeed');
    if (simulationSpeed) simulationSpeed.disabled = planIsRunning;
    const simulationScope = document.getElementById('simulationScope');
    if (simulationScope) simulationScope.disabled = laneSimulationRunning || planIsRunning;
    updateMapModeButton();
}

function updateMapModeButton() {
    const btn = document.getElementById('mapEditModeBtn');
    if (btn) btn.disabled = planUiMode !== 'plan' || planIsRunning;
}

function updateMapsSectionTitle() {
    const title = document.getElementById('mapsSectionTitle');
    if (!title) return;
    document.getElementById('mapsScreen')?.classList.toggle('plan-driving', planIsRunning);
    document.getElementById('mapsScreen')?.classList.toggle('plan-mode', planUiMode === 'plan' || planIsRunning);
    if (mapEditor) {
        setTimeout(() => mapEditor.invalidateSize(), 50);
    }
    if (planIsRunning) {
        const name = activePlanName || activeMapName || 'Plan';
        title.innerHTML = `<span class="drive-title"><span class="drive-indicator"></span><span>Fahre ${escapeHtml(name)}</span></span>`;
        return;
    }
    title.textContent = planUiMode === 'plan' && activePlanName
        ? `Plan ${activePlanName}`
        : 'Kartenverwaltung';
}

function setPlanStatus(message) {
    const el = document.getElementById('planStatus');
    if (el) el.textContent = message;
}

// Die Statuszeile oben liegt in einem zugeklappten <details> auf der
// Kartenseite. Ein Plan, der stehenbleibt, war dort dreimal unsichtbar
// (26.07., 02.08., 07.08.: heading_block mitten auf der Flaeche, "Fortsetzen"
// scheiterte an derselben Sperre und meldete es an dieselbe Stelle). Diese
// Meldungen gehoeren deshalb zusaetzlich in ein Banner ueber allen Screens.
function setPlanAlert(message) {
    const el = document.getElementById('planAlert');
    if (!el) return;
    if (!message) {
        planAlertDismissed = null;
        el.hidden = true;
        el.textContent = '';
        return;
    }
    if (message === planAlertDismissed) {
        el.hidden = true;
        return;
    }
    if (el.textContent !== message) el.textContent = message;
    el.hidden = false;
}

function dismissPlanAlert() {
    const el = document.getElementById('planAlert');
    if (!el || el.hidden) return;
    // Nur diese eine Meldung ausblenden - eine neue erscheint wieder.
    planAlertDismissed = el.textContent;
    el.hidden = true;
}

function planAlertText(plan, planState) {
    if (planBlockedMessage) return planBlockedMessage;
    if (planIsRunning) return null;
    if (['', 'idle', 'running', 'completed'].includes(planState)) return null;
    const detail = plan.last_error ? ` · ${plan.last_error}` : '';
    // Ein vom Benutzer ausgeloester Halt ohne Fehlertext ist keine Stoerung.
    if (!detail && ['paused', 'stopped', 'stopping'].includes(planState)) return null;
    // Nach einem Neustart des Dienstes ist die Segmentzahl unbekannt - dann
    // "Segment 3/0" zu schreiben wäre schlechter als nichts.
    const progress = plan.total
        ? ` · Segment ${plan.active_index || 0}/${plan.total}`
        : '';
    return `⛔ Plan gestoppt: ${planState}${progress}${detail}`;
}

function updateActivePlanLabel() {
    const el = document.getElementById('activePlanLabel');
    if (!el) return;
    if (!lanePreviewPlan) {
        el.textContent = 'Kein Plan geladen';
        return;
    }
    const name = lanePreviewPlan.map_name || lanePreviewPlan.name || activeMapName || 'Unbenannt';
    el.textContent = lanePreviewSource === 'saved'
        ? `${name} · gespeichert`
        : `${name} · Vorschau (ungespeichert)`;
}

function planSummaryText(plan) {
    const sequence = plan.segment_count ?? ((plan.sequence || []).length);
    const unsafe = plan.unsafe_transition_count || 0;
    const reverse = plan.reverse_segment_count ?? ((plan.sequence || []).filter(item => item.type === 'rest_lane' && item.direction === 'reverse').length);
    const total = plan.total_drive_length_m || plan.total_length_m || 0;
    return `${sequence || 0} Segmente · ${unsafe} unsafe · ${reverse} rückwärts · ${formatArea(total)} m`;
}

function updateVehiclePose(sensorData, navigationStatus, planExecutionStatus) {
    // Plan state and especially its error message must reach the user even
    // when there is no pose, no sensor payload or no open map - a plan that
    // stopped is exactly the moment those can be missing. Keep it ahead of
    // every early return below (a heading_block went unnoticed on 26.07.
    // because it was reported only after the vehicle marker was drawn).
    updatePlanStatusDisplay(navigationStatus, planExecutionStatus);
    if (!sensorData) return;
    const pose = normalizePose(sensorData);
    latestVehiclePose = pose;
    updateRtkStatus(sensorData);
    if (!mapEditor) return;
    if (!pose) return;
    const latLng = [pose.latitude, pose.longitude];
    if (!vehicleMarker) {
        vehicleMarker = L.marker(latLng, {
            icon: vehicleIcon(pose.heading_deg),
            zIndexOffset: 2000,
            interactive: false,
        }).addTo(mapEditor);
    } else {
        vehicleMarker.setLatLng(latLng);
        vehicleMarker.setIcon(vehicleIcon(pose.heading_deg));
    }
    const headingEnd = pointFromHeading(pose.latitude, pose.longitude, pose.heading_deg, 1.2);
    if (!vehicleHeadingLine) {
        vehicleHeadingLine = L.polyline([latLng, headingEnd], {
            color: '#ff00ff',
            weight: 3,
            opacity: 0.95,
        }).addTo(mapEditor);
    } else {
        vehicleHeadingLine.setLatLngs([latLng, headingEnd]);
    }
}

function updatePlanStatusDisplay(navigationStatus, planExecutionStatus) {
    const nav = navigationStatus || {};
    const plan = planExecutionStatus || {};
    latestPlanExecutionStatus = plan;
    planIsRunning = plan.running === true || plan.state === 'running';
    const planState = plan.state || '';
    if (['stopped', 'completed'].includes(planState)) {
        planResumeAvailable = false;
    } else {
        planResumeAvailable = plan.resume_available === true ||
            ['paused', 'rtk_lost'].includes(planState) ||
            (!planIsRunning && savedPlanHasResume(activeMapName));
    }
    if (planIsRunning && planUiMode !== 'plan') {
        enterPlanUiMode(remotePlanMapName(plan) || activePlanName || activeMapName || 'Plan');
    }
    adoptRemotePlan();
    updateMapModeButton();
    updateMapsSectionTitle();
    updateNoGoStatus(plan.nogo_status);
    const sourceIndex = plan.current_segment?.source_index;
    if (planIsRunning && sourceIndex !== null && sourceIndex !== undefined && Number.isFinite(Number(sourceIndex))) {
        updateLaneProgressForSegment(Number(sourceIndex));
    }
    if (planIsRunning) planBlockedMessage = null;
    setPlanAlert(planAlertText(plan, planState));
    if (planBlockedMessage) {
        // Eine abgelehnte Freigabe bleibt stehen, bis der Benutzer erneut
        // etwas auslöst - sie ist die Antwort auf seinen Klick.
        setPlanStatus(planBlockedMessage);
    } else if (plan.state && plan.state !== 'idle') {
        const segment = plan.current_segment || {};
        const progress = `${plan.active_index || 0}/${plan.total || 0}`;
        const errorDetail = plan.last_error ? ` · ${plan.last_error}` : '';
        const headingDetail = planHeadingWarning ? ` · ${planHeadingWarning}` : '';
        setPlanStatus(`Plan ${plan.state} · ${progress} · ${segment.mode || ''} ${segment.direction || ''}${errorDetail}${headingDetail}`.trim());
    } else if (nav.state && nav.state !== 'idle') {
        setPlanStatus(`Navigation ${nav.state} · ${nav.mode || ''} ${nav.direction || ''}`.trim());
    }
}

// Name des Plans, der im Fahrzeug offen ist. ``map_name`` steht immer im
// Status; ``summary`` gibt es nur, solange der Start im selben Dienstlauf
// liegt - aeltere Staende koennen deshalb nur die Zusammenfassung haben.
function remotePlanMapName(plan) {
    const status = plan || latestPlanExecutionStatus || {};
    return status.map_name || (status.summary && status.summary.map_name) || '';
}

// Ein Plan gilt als offen, solange er nicht sauber zu Ende oder bewusst
// beendet wurde: pausiert, wegen RTK stehengeblieben, nach Dienstneustart.
// In all diesen Faellen gehoert er auf jeden Bildschirm.
function remotePlanIsOpen(plan) {
    const status = plan || latestPlanExecutionStatus || {};
    const state = status.state || '';
    if (status.running === true || state === 'running') return true;
    return Boolean(state) && !['idle', 'completed', 'stopped'].includes(state);
}

// Den offenen Plan des Fahrzeugs in diese Oberflaeche holen. Wird bei jedem
// Statuseingang und beim Wechsel auf die Kartenseite aufgerufen, laedt aber
// nur einmal je Plan.
function adoptRemotePlan() {
    const plan = latestPlanExecutionStatus;
    const remoteName = remotePlanMapName(plan);
    if (!remoteName || !remotePlanIsOpen(plan)) {
        planAdoptedMapName = null;
        return;
    }
    if (planAdoptedMapName === remoteName || planAdoptionRunning || planLoadRunning) return;
    // Steht der richtige Plan schon da, ist nichts zu tun - eine eigene
    // Vorschau desselben Gebiets wird dagegen durch den gespeicherten Plan
    // ersetzt, denn gefahren wird der gespeicherte.
    if (lanePreviewPlan && lanePreviewSource === 'saved' && activeMapName === remoteName) {
        planAdoptedMapName = remoteName;
        return;
    }
    // Leaflet auf einer unsichtbaren Seite bekommt seine Groesse nicht mit und
    // zoomt daneben. Solange die Kartenseite zu ist, sieht ohnehin niemand
    // hin; beim Aufschlagen wird nachgeholt.
    if (!document.getElementById('mapsScreen')?.classList.contains('active')) return;
    if (Date.now() < planAdoptionRetryAfter) return;
    planAdoptionRunning = true;
    loadSavedPlan(remoteName)
        .then(loaded => {
            planAdoptedMapName = loaded ? remoteName : null;
            // Nach einem Fehlschlag nicht im Sekundentakt nachhaken.
            if (!loaded) planAdoptionRetryAfter = Date.now() + 15000;
        })
        .finally(() => {
            planAdoptionRunning = false;
        });
}

function selectedPlanStart() {
    if (!lanePreviewPlan) return null;
    const slider = document.getElementById('laneProgressSlider');
    const percent = Number(slider?.value || 0);
    const fraction = percent / 100;
    const position = pointAtPlanProgress(lanePreviewPlan, fraction);
    if (!position || position.segmentIndex === undefined) return null;
    return {
        segmentIndex: position.segmentIndex,
        coordinate: [position.lng, position.lat],
        percent,
    };
}

function updateLaneProgressForSegment(segmentIndex) {
    if (!lanePreviewPlan) return;
    const sequence = ((lanePreviewPlan.sequence && lanePreviewPlan.sequence.length) ? lanePreviewPlan.sequence : (lanePreviewPlan.lanes || []))
        .filter(segment => (segment.coordinates || []).length >= 2);
    const total = sequence.reduce((sum, segment) => sum + Number(segment.length_m || 0), 0);
    if (total <= 0) return;
    let travelled = 0;
    let activeSegment = null;
    for (const segment of sequence) {
        const currentIndex = Number(segment.segment_index ?? 0);
        if (currentIndex >= Number(segmentIndex)) {
            if (currentIndex === Number(segmentIndex)) activeSegment = segment;
            break;
        }
        travelled += Number(segment.length_m || 0);
    }
    if (!activeSegment) return;
    // Do not round-trip an exact segment boundary through a percentage. A
    // floating-point value a few micrometres below the boundary selects the
    // preceding ring. Move the live marker 5 cm into the actual source
    // segment, while the manually selected slider position remains exact.
    const segmentLength = Number(activeSegment.length_m || 0);
    const insideOffset = Math.min(0.05, Math.max(0, segmentLength / 2));
    updateLaneProgress(((travelled + insideOffset) / total) * 100);
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[char]);
}

function updateNoGoStatus(nogoStatus) {
    const el = document.getElementById('planNoGoStatus');
    if (!el) return;
    const status = nogoStatus || {};
    const state = status.state || 'unbekannt';
    el.textContent = state === 'ok' && typeof status.distance_m === 'number'
        ? `OK · ${formatArea(status.distance_m)} m`
        : state;
    if (state === 'stop') {
        el.style.color = '#ff2f7d';
    } else if (state === 'warning') {
        el.style.color = '#ffb000';
    } else if (state === 'ok' || state === 'disabled') {
        el.style.color = '#34a853';
    } else {
        el.style.color = '#ffffff';
    }
}

function updateRtkStatus(sensorData) {
    const gps = sensorData && sensorData.gps && typeof sensorData.gps === 'object' ? sensorData.gps : {};
    const status = String((sensorData && sensorData.rtk_status) || gps.rtk_status || 'unbekannt');
    rtkAvailable = ['RTK FIXED', 'FIXED'].includes(status.trim().toUpperCase());
    const dot = document.getElementById('rtkInfoStatus');
    if (dot) dot.className = `status-dot ${rtkAvailable ? 'active' : 'inactive'}`;
    const text = document.getElementById('rtkInfoStatusText');
    if (text) {
        // Der Punkt ist bewusst binaer (nur RTK FIXED ist gruen). Status-Text
        // und Satellitenzahl daneben zeigen, ob es gerade FLOAT/DGPS ist und
        // ob ueberhaupt genug Satelliten stehen - am Feldrand die erste Frage.
        const label = status.trim().toUpperCase().startsWith('RTK') ? status : `RTK ${status}`;
        const satellites = Number(gps.satellites);
        text.textContent = Number.isFinite(satellites) && satellites > 0
            ? `${label} · ${satellites} Sat`
            : label;
    }
    const indicator = document.getElementById('rtkInfoIndicator');
    if (indicator) indicator.title = rtkAvailable ? 'RTK-Fix verfügbar' : 'Kein RTK-Fix verfügbar';
    refreshPlanButtons();
}

function normalizePose(sensorData) {
    const gps = sensorData.gps && typeof sensorData.gps === 'object' ? sensorData.gps : {};
    const latitude = Number(sensorData.latitude ?? sensorData.lat ?? gps.lat ?? gps.latitude);
    const longitude = Number(sensorData.longitude ?? sensorData.lon ?? sensorData.lng ?? gps.lon ?? gps.lng ?? gps.longitude);
    const heading = Number(sensorData.heading_deg ?? sensorData.heading ?? gps.heading ?? 0);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
    return {latitude, longitude, heading_deg: Number.isFinite(heading) ? heading : 0};
}

function vehicleIcon(headingDeg) {
    const heading = Number(headingDeg || 0);
    return L.divIcon({
        className: '',
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        // Reine Anzeige: Klicks müssen zu den darunter liegenden Punkt-Markern
        // durchfallen, sonst ist ein Kartenpunkt unter dem Fahrzeugsymbol nicht
        // mehr bearbeitbar.
        html: `<div style="width:34px;height:34px;position:relative;pointer-events:none;transform:rotate(${heading}deg);">
            <div style="position:absolute;left:9px;top:2px;width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-bottom:24px solid #ff00ff;filter:drop-shadow(0 0 4px rgba(0,0,0,0.8));"></div>
            <div style="position:absolute;left:13px;top:15px;width:8px;height:8px;border-radius:50%;background:#ffffff;border:2px solid #111;"></div>
        </div>`,
    });
}

function pointFromHeading(latitude, longitude, headingDeg, distanceM) {
    const heading = headingDeg * Math.PI / 180;
    const dLat = Math.cos(heading) * distanceM / 6371000 * 180 / Math.PI;
    const dLon = Math.sin(heading) * distanceM / (6371000 * Math.cos(latitude * Math.PI / 180)) * 180 / Math.PI;
    return [latitude + dLat, longitude + dLon];
}

// Lane progress marker and segment highlighting
function updateLaneProgress(percent) {
    const value = Math.max(0, Math.min(100, Number(percent || 0)));
    document.getElementById('laneProgressValue').textContent = `${value.toFixed(1).replace('.', ',')}%`;
    const slider = document.getElementById('laneProgressSlider');
    if (slider && Number(slider.value) !== value) slider.value = value;
    if (!lanePreviewPlan || !mapEditor) return;
    const position = pointAtPlanProgress(lanePreviewPlan, value / 100);
    if (!position) return;
    highlightSequenceSegment(position);
    if (!laneProgressMarker) {
        laneProgressMarker = L.circleMarker([position.lat, position.lng], {
            radius: 9,
            color: '#000',
            weight: 2,
            fillColor: '#ff00ff',
            fillOpacity: 1.0,
        }).addTo(mapEditor);
    } else {
        laneProgressMarker.setLatLng([position.lat, position.lng]);
    }
    const travelled = formatArea(position.travelledM || 0);
    const total = formatArea(position.totalM || 0);
    const laneTravelled = formatArea(position.laneTravelledM || 0);
    const laneLength = formatArea(position.laneLengthM || 0);
    const detail = document.getElementById('laneProgressDetail');
    if (detail) {
        if (position.segmentType === 'connector') {
            detail.textContent = `${travelled} m / ${total} m · Übergang ${position.fromLaneIndex + 1} → ${position.toLaneIndex + 1}: ${laneTravelled} m / ${laneLength} m`;
        } else if (position.segmentType === 'rest_lane') {
            detail.textContent = `${travelled} m / ${total} m · Restbahn ${position.restIndex + 1} ${position.direction === 'reverse' ? 'rückwärts' : 'vorwärts'}: ${laneTravelled} m / ${laneLength} m`;
        } else if (position.segmentType === 'sub_contour') {
            detail.textContent = `${travelled} m / ${total} m · Sub-Kontur ${position.laneIndex + 1}: ${laneTravelled} m / ${laneLength} m`;
        } else {
            detail.textContent = `${travelled} m / ${total} m · Ring ${position.laneIndex + 1}: ${laneTravelled} m / ${laneLength} m`;
        }
    }
    let tooltipPrefix = `Ring ${position.laneIndex + 1}`;
    if (position.segmentType === 'connector') {
        tooltipPrefix = `Übergang ${position.fromLaneIndex + 1} → ${position.toLaneIndex + 1}`;
    } else if (position.segmentType === 'rest_lane') {
        tooltipPrefix = `Restbahn ${position.restIndex + 1} · ${position.direction === 'reverse' ? 'rückwärts' : 'vorwärts'}`;
    } else if (position.segmentType === 'sub_contour') {
        tooltipPrefix = `Sub-Kontur ${position.laneIndex + 1}`;
    }
    laneProgressMarker.bindTooltip(`${tooltipPrefix} · ${value.toFixed(1).replace('.', ',')}%`, {permanent: false});
}

function pointAtPlanProgress(plan, fraction) {
    const sequence = ((plan.sequence && plan.sequence.length) ? plan.sequence : (plan.lanes || []))
        .filter(segment => (segment.coordinates || []).length >= 2);
    if (!sequence.length) return null;
    const total = sequence.reduce((sum, segment) => sum + Number(segment.length_m || 0), 0);
    if (total <= 0) {
        const first = sequence[0].coordinates[0];
        return {lat: first[1], lng: first[0], laneIndex: 0, segmentType: sequence[0].type || 'contour', segmentIndex: sequence[0].segment_index || 0, travelledM: 0, totalM: 0, laneTravelledM: 0, laneLengthM: 0};
    }
    const target = total * Math.max(0, Math.min(1, fraction));
    let remaining = target;
    for (const segment of sequence) {
        const segmentLength = Number(segment.length_m || 0);
        // An exact sequence boundary belongs to the segment that starts
        // there. Otherwise the live status highlights the preceding ring
        // while the executor is already driving the first rest lane.
        if (remaining < segmentLength || segment === sequence[sequence.length - 1]) {
            return pointAtLineDistance(segment.coordinates, remaining, segment, target, total, segmentLength);
        }
        remaining -= segmentLength;
    }
    const lastSegment = sequence[sequence.length - 1];
    const lastPoint = lastSegment.coordinates[lastSegment.coordinates.length - 1];
    return {
        lat: lastPoint[1],
        lng: lastPoint[0],
        laneIndex: lastSegment.lane_index || sequence.length - 1,
        fromLaneIndex: lastSegment.from_lane_index || 0,
        toLaneIndex: lastSegment.to_lane_index || 0,
        segmentType: lastSegment.type || 'contour',
        segmentIndex: lastSegment.segment_index || sequence.length - 1,
        travelledM: total,
        totalM: total,
        laneTravelledM: Number(lastSegment.length_m || 0),
        laneLengthM: Number(lastSegment.length_m || 0)
    };
}

function pointAtLineDistance(coords, distanceM, segment, travelledM = distanceM, totalM = 0, laneLengthM = 0) {
    if (!coords.length) return null;
    const segmentInfo = {
        laneIndex: segment.lane_index || 0,
        restIndex: segment.rest_index || 0,
        direction: segment.direction || 'forward',
        fromLaneIndex: segment.from_lane_index || 0,
        toLaneIndex: segment.to_lane_index || 0,
        segmentType: segment.type || 'contour',
        segmentIndex: segment.segment_index || 0,
    };
    if (distanceM <= 0 || coords.length === 1) {
        return {lat: coords[0][1], lng: coords[0][0], ...segmentInfo, travelledM, totalM, laneTravelledM: 0, laneLengthM};
    }
    let remaining = distanceM;
    for (let i = 0; i < coords.length - 1; i += 1) {
        const a = coords[i];
        const b = coords[i + 1];
        const segment = distanceLatLngM(a, b);
        if (remaining <= segment) {
            const t = segment <= 0 ? 0 : remaining / segment;
            return {
                lat: a[1] + (b[1] - a[1]) * t,
                lng: a[0] + (b[0] - a[0]) * t,
                ...segmentInfo,
                travelledM,
                totalM,
                laneTravelledM: distanceM,
                laneLengthM
            };
        }
        remaining -= segment;
    }
    const last = coords[coords.length - 1];
    return {lat: last[1], lng: last[0], ...segmentInfo, travelledM, totalM, laneTravelledM: distanceM, laneLengthM};
}

function highlightSequenceSegment(position) {
    lanePreviewLaneLayers.forEach((layer, index) => {
        if (!layer) return;
        const active = position.segmentType !== 'connector' && index === position.laneIndex;
        const subContour = lanePreviewPlan && (lanePreviewPlan.lanes || [])[index]?.type === 'sub_contour';
        layer.setStyle({
            color: active ? '#fff3a3' : (subContour ? '#ffcf5a' : '#ffe66d'),
            weight: active ? 5 : (subContour ? 3 : 2),
            opacity: active ? 1.0 : 0.82,
            dashArray: subContour ? '10 4' : null,
        });
        if (active) layer.bringToFront();
    });
    lanePreviewConnectorLayers.forEach((layer, index) => {
        if (!layer) return;
        const active = position.segmentType === 'connector' && index === position.segmentIndex;
        layer.setStyle({
            color: active ? '#ffffff' : '#e8f7ff',
            weight: active ? 6 : 4,
            opacity: active ? 1.0 : 0.75,
            dashArray: '10 7'
        });
        if (active) layer.bringToFront();
    });
    lanePreviewRestLayers.forEach((layer, index) => {
        if (!layer) return;
        const active = position.segmentType === 'rest_lane' && index === position.restIndex;
        const reverse = layer.options.dashArray;
        layer.setStyle({
            color: active ? '#ffffff' : (reverse ? '#7fdcff' : '#9fffe0'),
            weight: active ? 6 : 3,
            opacity: active ? 1.0 : 0.85,
            dashArray: reverse ? '8 6' : null,
        });
        if (active) layer.bringToFront();
    });
    if (laneProgressMarker) laneProgressMarker.bringToFront();
}

// Map analysis, sub-map overlays, and formatting helpers
function distanceLatLngM(a, b) {
    const lat1 = a[1] * Math.PI / 180;
    const lat2 = b[1] * Math.PI / 180;
    const dLat = lat2 - lat1;
    const dLon = (b[0] - a[0]) * Math.PI / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function setPlannerStatus(message) {
    const el = document.getElementById('plannerStatus');
    if (el) el.textContent = message;
}

function loadMapAnalysis(name) {
    if (!document.getElementById('mainMapsOnlyToggle').checked || !name || name.toLowerCase().startsWith('sub_')) {
        clearMapAnalysis();
        return;
    }
    fetch(`/api/mapping/maps/${encodeURIComponent(name)}/analysis`)
        .then(response => response.json().then(data => ({ok: response.ok, data})))
        .then(result => {
            if (!result.ok || result.data.success === false) {
                clearMapAnalysis(result.data.error || 'Flächenanalyse fehlgeschlagen');
                return;
            }
            renderSubMaps(result.data.subs || []);
            renderAreaSummary(result.data.area || {}, result.data.subs || []);
        });
}

function renderSubMaps(subs) {
    subMapLayers.forEach(layer => layer.remove());
    subMapLayers = [];
    if (!mapEditor) return;
    subs.forEach(item => {
        const points = boundaryPointsFromGeoJSON(item.map);
        if (!points.length) return;
        const layer = L.polygon(points.map(point => [point.latitude, point.longitude]), {
            color: '#ff6b4a',
            weight: 2,
            fillColor: '#ff2d2d',
            fillOpacity: 0.28,
            dashArray: '6 6'
        }).addTo(mapEditor);
        layer.bindTooltip(item.name);
        subMapLayers.push(layer);
    });
}

function renderAreaSummary(area, subs) {
    const exactText = area.exact === false ? ' (einfach)' : '';
    document.getElementById('areaSummary').innerHTML = `
        <div class="area-row"><span>Brutto</span><strong>${formatArea(area.gross_m2)} m²</strong></div>
        <div class="area-row"><span>Ausgeschlossen</span><strong>${formatArea(area.excluded_m2)} m²</strong></div>
        <div class="area-row"><span>Netto</span><strong>${formatArea(area.net_m2)} m²${exactText}</strong></div>
        <div class="sub-list" id="subMapList">${formatSubList(area.subs || subs)}</div>
    `;
}

function clearMapAnalysis(message = 'Keine Hauptkarte geladen') {
    subMapLayers.forEach(layer => layer.remove());
    subMapLayers = [];
    document.getElementById('areaSummary').innerHTML = `
        <div class="area-row"><span>Brutto</span><strong>-- m²</strong></div>
        <div class="area-row"><span>Ausgeschlossen</span><strong>-- m²</strong></div>
        <div class="area-row"><span>Netto</span><strong>-- m²</strong></div>
        <div class="sub-list" id="subMapList">${message}</div>
    `;
}

function formatArea(value) {
    const number = Number(value || 0);
    return number.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1});
}

function formatSubList(subs) {
    if (!subs || !subs.length) return 'Keine Sub-Flächen gefunden';
    return subs.map(item => `${item.name}: ${formatArea(item.area_m2)} m²`).join('<br>');
}

function pointIcon(active) {
    const dotSize = active ? 18 : 14;
    const hitSize = 40;
    const inset = (hitSize - dotSize) / 2;
    const fill = active ? '#ffb000' : '#34a853';
    const border = active ? '#ffffff' : '#ffd700';
    return L.divIcon({
        className: '',
        iconSize: [hitSize, hitSize],
        iconAnchor: [hitSize / 2, hitSize / 2],
        html: `<div style="width:${hitSize}px;height:${hitSize}px;cursor:move;touch-action:none;position:relative;"><div style="position:absolute;left:${inset}px;top:${inset}px;width:${dotSize}px;height:${dotSize}px;border-radius:50%;background:${fill};border:2px solid ${border};box-shadow:0 0 8px rgba(0,0,0,0.65);"></div></div>`
    });
}

window.MappingEditor = {
    initMapEditor,
    refreshMapList,
    loadSelectedMap,
    loadMap,
    clearMapEditor,
    setMapBaseLayer,
    saveEditedMap,
    renameSelectedMap,
    deleteSelectedMap,
    deleteSelectedPoint,
    generateLanePreview,
    saveLanePlan,
    simulateLanePlan,
    toggleLaneSimulationPause,
    stopLaneSimulation,
    clearLaneSimulation,
    clearLanePreview,
    updateLaneProgress,
    refreshPlanList,
    loadSavedPlan,
    playLoadedPlan,
    pausePlanExecution,
    stopPlanExecution,
    returnToMapEditMode,
    updateVehiclePose,
    adoptRemotePlan,
    dismissPlanAlert,
};
