function renderMachineCards() {
  var machineCardGrid = document.getElementById('machineCardGrid');

  if (filteredMachinesList.length === 0) {
    machineCardGrid.innerHTML = '<div class="health-empty">No machine profiles are available for your account.</div>';
    return;
  }

  machineCardGrid.innerHTML = filteredMachinesList.map(function(machine, index) {
    var stats = getMachineHealthStats(machine);
    var bestScoreText = stats.bestScore !== null ? Math.round(stats.bestScore) : 'n/a';
    var scoreColor = getHealthColorFromScore(stats.bestScore);
    var machineBadges = machine.privileged_access_required
      ? '<div class="machine-card-badges">' +
          '<span class="mlhub-badge is-accent">Privileged</span>' +
        '</div>'
      : '';
    return '' +
      '<button type="button" class="machine-card ' + (index === selectedMachineIndex ? 'is-active' : '') + '" data-machine-index="' + index + '">' +
        '<div class="machine-card-head">' +
          '<div>' +
            '<h4 class="machine-card-name">' + escapeHtml(machine.codename || 'Unnamed') + '</h4>' +
            '<div class="machine-card-subtitle">' + escapeHtml(machine.cpu_model || 'Hardware profile') + '</div>' +
          '</div>' +
          '<div class="machine-card-health">' +
            '<span class="machine-card-health-dot" style="background:' + escapeHtml(scoreColor) + ';"></span>' +
            '<span>Best health: ' + escapeHtml(bestScoreText) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="machine-spec-grid">' +
          '<div class="machine-spec"><span class="machine-spec-label">GPUs</span><span class="machine-spec-value">' + escapeHtml(getMachineGpuText(machine)) + '</span></div>' +
          '<div class="machine-spec"><span class="machine-spec-label">CPU</span><span class="machine-spec-value">' + escapeHtml(getMachineCpuText(machine)) + '</span></div>' +
          '<div class="machine-spec"><span class="machine-spec-label">RAM</span><span class="machine-spec-value">' + escapeHtml(getMachineRamText(machine)) + '</span></div>' +
        '</div>' +
        machineBadges +
      '</button>';
  }).join('');

  Array.prototype.forEach.call(machineCardGrid.querySelectorAll('[data-machine-index]'), function(button) {
    button.addEventListener('click', function() {
      setSelectedMachine(Number(button.getAttribute('data-machine-index')));
    });
  });
}

function renderMachineDetails(machine) {
  var detailsDiv = document.getElementById('machineDetails');
  if (!machine) {
    detailsDiv.innerHTML = '<div class="health-empty">No machine selected.</div>';
    return;
  }

  var sharingAvailable = machineSupportsSharing(machine);
  var sharingForced = isSharingForced(machine);
  var sharedAccessRequested = sharingAvailable ? (sharingForced ? true : preferredSharedAccessRequested) : false;
  var sharingMessage = sharingAvailable
    ? (sharingForced
        ? 'Your current privileges do not allow exclusive access, so session sharing is required for this launch.'
        : 'Privileged users can clear this box to hold the selected machine exclusively.')
    : 'This machine type does not expose shared-session scheduling.';
  var sharingNoteClass = sharingForced ? ' is-warning' : (sharingAvailable ? '' : ' is-muted');

  var sessionOptionsMarkup =
    '<input type="hidden" id="sharedAccessValue" name="sharedAccessValue" value="' + (sharedAccessRequested ? 'true' : 'false') + '">' +
    '<div id="sessionOptionsCard" class="session-options' + (sharedAccessRequested ? ' is-enabled' : '') + (sharingForced || !sharingAvailable ? ' is-disabled' : '') + '">' +
      '<label class="share-toggle' + (sharingForced || !sharingAvailable ? ' is-disabled' : '') + '" for="sharedAccess">' +
        '<input class="form-check-input" type="checkbox" id="sharedAccess"' + (sharedAccessRequested ? ' checked' : '') + (sharingForced || !sharingAvailable ? ' disabled' : '') + '>' +
        '<span>' +
          '<span class="share-toggle-title">Allow session sharing</span>' +
          '<span class="share-toggle-copy">' + escapeHtml(sharingAvailable
            ? 'Keep this enabled if you are fine sharing the selected machine with another active session.'
            : 'Shared session placement is not available for this machine type.') + '</span>' +
        '</span>' +
      '</label>' +
      '<div class="session-note' + sharingNoteClass + '"><strong>Note:</strong> ' + escapeHtml(sharingMessage) + '</div>' +
    '</div>';

  detailsDiv.innerHTML =
    '<div class="mlhub-card-header">' +
      '<div>' +
        '<h3 class="mlhub-card-title">Allow session sharing</h3>' +
        '<p class="mlhub-card-copy">Session sharing is enabled by default so users do not request exclusive nodes by mistake.</p>' +
      '</div>' +
    '</div>' +
    '<p class="mlhub-card-copy">Selected machine type: ' + escapeHtml(machine.codename || 'Unnamed') + '.</p>' +
    sessionOptionsMarkup;

  var sharedAccess = document.getElementById('sharedAccess');
  if (sharedAccess) {
    sharedAccess.addEventListener('change', function() {
      preferredSharedAccessRequested = !!(sharedAccess.checked && !sharedAccess.disabled);
      renderSharingState();
    });
  }
  renderSharingState();
}

function buildNodeDetails(snapshot) {
  if (!snapshot) {
    return '<div class="health-empty">This node is offline or has not reported telemetry yet.</div>';
  }

  var cpuText = snapshot.cpu_usage_pct !== null && snapshot.cpu_usage_pct !== undefined
    ? formatPercent(snapshot.cpu_usage_pct)
    : 'n/a';
  var ramText = snapshot.ram_used_bytes !== null && snapshot.ram_total_bytes !== null
    ? bytesToGiB(snapshot.ram_used_bytes) + ' / ' + bytesToGiB(snapshot.ram_total_bytes)
    : 'n/a';
  var fitnessText = snapshot.fitness_score !== null && snapshot.fitness_score !== undefined
    ? Number(snapshot.fitness_score).toFixed(1)
    : 'n/a';
  var gpuInfo = Array.isArray(snapshot.gpus) && snapshot.gpus.length > 0
    ? snapshot.gpus.map(function(gpu) {
        return '' +
          '<div class="health-gpu-item">' +
            '<div class="health-gpu-title">GPU ' + escapeHtml(gpu.index) + '</div>' +
            '<div class="health-gpu-copy">' +
              'VRAM: ' + escapeHtml(bytesToGiB(gpu.memory_used_bytes)) + ' / ' + escapeHtml(bytesToGiB(gpu.memory_total_bytes)) + '<br>' +
              'Utilization: ' + escapeHtml(formatPercent(gpu.utilization_gpu_pct)) +
            '</div>' +
          '</div>';
      }).join('')
    : '<div class="health-empty">GPU metrics unavailable.</div>';

  var errorMarkup = snapshot.last_error
    ? '<div class="health-error"><strong>Last error:</strong> ' + escapeHtml(snapshot.last_error) + '</div>'
    : '';

  return '' +
    '<div class="health-detail-grid">' +
      '<div class="health-detail-card"><span class="health-detail-label">Fitness</span><span class="health-detail-value">' + escapeHtml(fitnessText) + '</span></div>' +
      '<div class="health-detail-card"><span class="health-detail-label">RAM used</span><span class="health-detail-value">' + escapeHtml(ramText) + '</span></div>' +
      '<div class="health-detail-card"><span class="health-detail-label">CPU usage</span><span class="health-detail-value">' + escapeHtml(cpuText) + '</span></div>' +
    '</div>' +
    '<div class="health-gpu-list">' + gpuInfo + '</div>' +
    errorMarkup;
}

function renderMachineHealthTable(machine) {
  var tableContainer = document.getElementById('machineHealthTable');
  if (!machine || getMachineInstances(machine).length === 0) {
    tableContainer.innerHTML = '<div class="health-empty">No machine instances available for this profile.</div>';
    return;
  }

  if (expandedHealthInstanceId && !nodeHealth[expandedHealthInstanceId] && !getMachineInstances(machine).some(function(instance) { return instance.instance_id === expandedHealthInstanceId; })) {
    expandedHealthInstanceId = null;
  }

  tableContainer.innerHTML =
    '<div class="health-list">' +
    getMachineInstances(machine).map(function(machineInstance) {
      var snapshot = nodeHealth[machineInstance.instance_id];
      var offline = isOfflineSnapshot(snapshot);
      var score = !offline ? Number(snapshot.fitness_score) : null;
      var scoreText = score !== null ? Math.round(score) : 'OFFLINE';
      var barWidth = score !== null ? Math.max(8, Math.min(100, score)) : 8;
      var color = getHealthColor(snapshot);
      var statusMeta = getStatusMeta(snapshot);
      var isOpen = expandedHealthInstanceId === machineInstance.instance_id;
      var subtitle = offline ? 'Node is currently unavailable' : 'Click to inspect current load';

      return '' +
        '<div class="health-item ' + (isOpen ? 'is-open' : '') + '">' +
          '<button type="button" class="health-trigger" data-instance-id="' + escapeHtml(machineInstance.instance_id) + '" aria-expanded="' + (isOpen ? 'true' : 'false') + '">' +
            '<div class="health-main">' +
              '<div class="health-host">' + escapeHtml(displayHostname(machineInstance)) + '</div>' +
              '<div class="health-subtitle">' + escapeHtml(subtitle) + '</div>' +
              '<div class="health-bar"><div class="health-bar-fill" style="width:' + escapeHtml(barWidth) + '%; background:' + escapeHtml(color) + ';"></div></div>' +
            '</div>' +
            '<div class="health-meta">' +
              '<span class="health-status-pill ' + escapeHtml(statusMeta.className) + '">' + escapeHtml(statusMeta.label) + '</span>' +
              '<span class="health-score-inline' + (offline ? ' is-text' : '') + '" style="color:' + escapeHtml(color) + ';">' + escapeHtml(scoreText) + '</span>' +
              '<span class="health-chevron">&#8250;</span>' +
            '</div>' +
          '</button>' +
          '<div class="health-detail">' + buildNodeDetails(snapshot) + '</div>' +
        '</div>';
    }).join('') +
    '</div>';

  Array.prototype.forEach.call(tableContainer.querySelectorAll('.health-trigger'), function(button) {
    button.addEventListener('click', function() {
      var instanceId = button.getAttribute('data-instance-id');
      expandedHealthInstanceId = expandedHealthInstanceId === instanceId ? null : instanceId;
      renderMachineHealthTable(filteredMachinesList[selectedMachineIndex]);
    });
  });
}

function renderSharingState() {
  var sharedAccess = document.getElementById('sharedAccess');
  var sharedAccessValue = document.getElementById('sharedAccessValue');
  var sessionOptionsCard = document.getElementById('sessionOptionsCard');
  if (!sharedAccess || !sharedAccessValue || !sessionOptionsCard) {
    return;
  }
  sharedAccessValue.value = sharedAccess.checked ? 'true' : 'false';
  sessionOptionsCard.classList.toggle('is-enabled', sharedAccess.checked);
  sessionOptionsCard.classList.toggle('is-disabled', sharedAccess.disabled);
}

function renderSelectedMachine() {
  var machine = filteredMachinesList[selectedMachineIndex];
  renderMachineCards();
  renderMachineDetails(machine);
  renderMachineHealthTable(machine);
}

function setSelectedMachine(index) {
  if (filteredMachinesList.length === 0) {
    return;
  }
  selectedMachineIndex = Math.max(0, Math.min(filteredMachinesList.length - 1, Number(index) || 0));
  expandedHealthInstanceId = null;
  document.getElementById('machineSelect').value = String(selectedMachineIndex);
  renderSelectedMachine();
}

function populateMachineOptions() {
  var machineSelect = document.getElementById('machineSelect');
  machineSelect.innerHTML = '';
  filteredMachinesList = machines;

  if (filteredMachinesList.length === 0) {
    var opt = document.createElement('option');
    opt.textContent = 'No machines available';
    opt.value = '';
    opt.disabled = true;
    machineSelect.appendChild(opt);
    document.getElementById('machineCardGrid').innerHTML = '<div class="health-empty">No machine profiles are available for your account.</div>';
    document.getElementById('machineDetails').innerHTML = '<div class="health-empty">No machine selected.</div>';
    document.getElementById('machineHealthTable').innerHTML = '<div class="health-empty">No health data available.</div>';
    return;
  }

  filteredMachinesList.forEach(function(machine, index) {
    var option = document.createElement('option');
    option.value = index;
    option.textContent = machine.codename || ('Machine ' + (index + 1));
    machineSelect.appendChild(option);
  });

  machineSelect.value = '0';
  selectedMachineIndex = 0;
  renderSelectedMachine();
}

function updateMachineDetails() {
  setSelectedMachine(document.getElementById('machineSelect').value);
}

function initializeMachineForm() {
  populateMachineOptions();

  var hostForm = document.getElementById('machineSelect').form;
  if (hostForm) {
    Array.prototype.forEach.call(hostForm.querySelectorAll('button[type="submit"], input[type="submit"]'), function(button) {
      button.classList.add('mlhub-submit-button');
    });
  }
}

initializeMachineForm();
