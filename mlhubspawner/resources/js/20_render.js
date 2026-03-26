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
  var selectedMachineInstance;
  if (!machine) {
    detailsDiv.innerHTML = '<div class="health-empty">No machine selected.</div>';
    return;
  }

  var sharingAvailable = machineSupportsSharing(machine);
  var sharingForced = isSharingForced(machine);
  var sharedAccessRequested = getSharedAccessRequested(machine);
  var sharingMessage = sharingAvailable
    ? (sharingForced
        ? 'Your current privileges do not allow exclusive access, so session sharing is required for this launch.'
        : 'Privileged users can clear this box to hold the selected machine exclusively.')
    : 'This machine type does not expose shared-session scheduling.';
  var sharingNoteClass = sharingForced ? ' is-warning' : (sharingAvailable ? '' : ' is-muted');
  selectedMachineInstance = getSelectedMachineInstance(machine);

  var sessionOptionsMarkup =
    '<input type="hidden" id="sharedAccessValue" name="sharedAccessValue" value="' + (sharedAccessRequested ? 'true' : 'false') + '">' +
    '<input type="hidden" id="machineInstanceId" name="machineInstanceId" value="' + escapeHtml(selectedMachineInstance ? selectedMachineInstance.instance_id : '') + '">' +
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
    sessionOptionsMarkup;

  var sharedAccess = document.getElementById('sharedAccess');
  if (sharedAccess) {
    sharedAccess.addEventListener('change', function() {
      preferredSharedAccessRequested = !!(sharedAccess.checked && !sharedAccess.disabled);
      syncSelectedMachineInstance(machine);
      renderSelectedMachine();
    });
  }
  renderSharingState();
}

function formatAssignedUserCount(machineInstance) {
  var assignedUserCount = machineInstance && machineInstance.assigned_user_count !== undefined
    ? Number(machineInstance.assigned_user_count)
    : 0;
  var label = assignedUserCount === 1 ? 'person assigned' : 'people assigned';
  return assignedUserCount + ' ' + label;
}

function getAssignedUsers(machineInstance) {
  if (!machineInstance || !Array.isArray(machineInstance.assigned_users)) {
    return [];
  }

  return machineInstance.assigned_users;
}

function formatAssignedDuration(durationSeconds) {
  var totalSeconds = Math.max(0, Math.floor(Number(durationSeconds) || 0));
  var days = Math.floor(totalSeconds / 86400);
  var hours = Math.floor((totalSeconds % 86400) / 3600);
  var minutes = Math.floor((totalSeconds % 3600) / 60);
  var seconds = totalSeconds % 60;

  if (days > 0) {
    return days + 'd ' + hours + 'h';
  }
  if (hours > 0) {
    return hours + 'h ' + minutes + 'm';
  }
  if (minutes > 0) {
    return minutes + 'm ' + seconds + 's';
  }
  return seconds + 's';
}

function buildAssignmentsTableMarkup(machineInstance) {
  var assignedUsers = getAssignedUsers(machineInstance);
  var tableBodyMarkup;

  if (assignedUsers.length === 0) {
    tableBodyMarkup = '<div class="health-assigned-users-empty">No current holders</div>';
  } else {
    tableBodyMarkup = '' +
      '<div class="health-assignments-table-wrap">' +
        '<table class="health-assignments-table">' +
          '<thead>' +
            '<tr>' +
              '<th scope="col">Username</th>' +
              '<th scope="col">Access</th>' +
              '<th scope="col">Assigned for</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' +
            assignedUsers.map(function(assignedUser) {
              var accessLabel = assignedUser.shared_access_enabled ? 'Shared' : 'Exclusive';
              return '' +
                '<tr>' +
                  '<td>' + escapeHtml(assignedUser.username || 'Unknown') + '</td>' +
                  '<td><span class="health-assignment-mode ' + (assignedUser.shared_access_enabled ? 'is-shared' : 'is-exclusive') + '">' + escapeHtml(accessLabel) + '</span></td>' +
                  '<td>' + escapeHtml(formatAssignedDuration(assignedUser.assigned_duration_seconds)) + '</td>' +
                '</tr>';
            }).join('') +
          '</tbody>' +
        '</table>' +
      '</div>';
  }

  return '' +
    '<div class="health-assignments-panel">' +
      '<div class="health-assignments-header">' +
        '<div>' +
          '<div class="health-assignments-title">Assignments</div>' +
          '<div class="health-assignments-copy">Current holders on this node.</div>' +
        '</div>' +
        '<div class="health-assignments-count">' + escapeHtml(formatAssignedUserCount(machineInstance)) + '</div>' +
      '</div>' +
      tableBodyMarkup +
    '</div>';
}

function buildNodeHeaderBadges(machine, machineInstance, isRecommended) {
  var potentiallyUnavailable = isMachineInstancePotentiallyUnavailable(machine, machineInstance);
  var badgeMarkup = '';

  if (isRecommended) {
    badgeMarkup += '<span class="mlhub-badge is-accent">Recommended</span>';
  }

  badgeMarkup += '<span class="mlhub-badge ' + (potentiallyUnavailable ? 'is-muted' : 'is-cyan') + '">' + (potentiallyUnavailable ? 'Potentially unavailable' : 'Eligible now') + '</span>';

  return badgeMarkup;
}

function buildHealthScoreCardStyle(score) {
  var colorChannels = getFitnessColorChannels(score);

  return '' +
    '--health-score-border:' + getRgbaString(colorChannels, 0.28) + ';' +
    '--health-score-bg-strong:' + getRgbaString(colorChannels, 0.18) + ';' +
    '--health-score-bg-soft:' + getRgbaString(colorChannels, 0.08) + ';' +
    '--health-score-shadow:' + getRgbaString(colorChannels, 0.14) + ';' +
    '--health-score-value:' + getRgbaString(colorChannels, 1) + ';';
}

function buildLaunchSummaryCardStyle(snapshot) {
  var fitnessScore = snapshot && snapshot.fitness_score !== null && snapshot.fitness_score !== undefined
    ? Number(snapshot.fitness_score)
    : null;
  var colorChannels = getFitnessColorChannels(fitnessScore);

  return '' +
    '--launch-summary-border:' + getRgbaString(colorChannels, 0.34) + ';' +
    '--launch-summary-bg-strong:' + getRgbaString(colorChannels, 0.22) + ';' +
    '--launch-summary-bg-soft:' + getRgbaString(colorChannels, 0.12) + ';' +
    '--launch-summary-shadow:' + getRgbaString(colorChannels, 0.16) + ';';
}

function buildLaunchSummaryStat(label, value, extraClassName) {
  return '' +
    '<div class="launch-summary-stat' + (extraClassName ? ' ' + extraClassName : '') + '">' +
      '<div class="launch-summary-stat-label">' + escapeHtml(label) + '</div>' +
      '<div class="launch-summary-stat-value">' + escapeHtml(value) + '</div>' +
    '</div>';
}

function renderLaunchSummaryCard(machine) {
  var summaryContainer = document.getElementById('launchSummaryCard');
  var selectedMachineInstance;
  var snapshot;
  var fitnessText;
  var fitnessCopy = 'Unavailable';
  var availabilityCopy = '';
  var sharingCopy = '';
  var assignedPeopleCopy = '';

  if (!summaryContainer) {
    return;
  }

  selectedMachineInstance = getSelectedMachineInstance(machine);
  if (!machine || !selectedMachineInstance) {
    summaryContainer.classList.remove('is-populated');
    summaryContainer.removeAttribute('style');
    summaryContainer.innerHTML = '<div class="health-empty">Choose a node to preview where your session will launch.</div>';
    return;
  }

  snapshot = nodeHealth[selectedMachineInstance.instance_id];
  fitnessText = snapshot && snapshot.fitness_score !== null && snapshot.fitness_score !== undefined
    ? Number(snapshot.fitness_score).toFixed(1)
    : null;
  if (fitnessText !== null) {
    fitnessCopy = fitnessText;
  }
  if (isMachineInstancePotentiallyUnavailable(machine, selectedMachineInstance)) {
    availabilityCopy = ' Availability will be rechecked when the launch starts.';
  }
  if (!machineSupportsSharing(machine)) {
    sharingCopy = 'Not available for this machine type';
  } else {
    sharingCopy = getSharedAccessRequested(machine) ? 'Enabled' : 'Disabled';
  }
  assignedPeopleCopy = formatAssignedUserCount(selectedMachineInstance);

  summaryContainer.classList.add('is-populated');
  summaryContainer.setAttribute('style', buildLaunchSummaryCardStyle(snapshot));
  summaryContainer.innerHTML =
    '<div class="mlhub-card-header">' +
      '<div>' +
        '<h3 class="mlhub-card-title">Launch summary</h3>' +
        '<p class="mlhub-card-copy">These are the launch settings that would be used if you start now.</p>' +
      '</div>' +
    '</div>' +
    '<div class="launch-summary-grid">' +
      buildLaunchSummaryStat('Machine type', machine.codename || 'Unnamed', 'is-wide') +
      buildLaunchSummaryStat('Instance', displayHostname(selectedMachineInstance), 'is-wide') +
      buildLaunchSummaryStat('Session sharing', sharingCopy, '') +
      buildLaunchSummaryStat('Fitness', fitnessCopy, '') +
      buildLaunchSummaryStat('People assigned', assignedPeopleCopy, '') +
    '</div>' +
    '<div class="launch-summary-copy">The launch target is currently selected from the visible nodes for this machine profile.' + escapeHtml(availabilityCopy) + '</div>';
}

function getMaskedSshGatewayPassword(password) {
  return password ? new Array(String(password).length + 1).join('\u2022') : 'Unavailable';
}

function renderSshGatewayCard() {
  var container = document.getElementById('sshGatewayCard');
  var gatewayHost;
  var gatewayPort;
  var gatewayUsername;
  var gatewayPassword;
  var passwordDisplay;
  var toggleLabel;
  var vpnGuideUrl = 'https://www.cs.ubbcluj.ro/internal/itmanual/wireguard/wireguard.html';

  if (!container) {
    return;
  }

  gatewayHost = sshGatewayContext.host || '';
  gatewayPort = sshGatewayContext.port || '';
  gatewayUsername = sshGatewayContext.username || '';
  gatewayPassword = sshGatewayContext.password || '';

  if (!gatewayUsername || !gatewayPassword || !gatewayHost || !gatewayPort) {
    container.classList.remove('is-populated');
    container.innerHTML = '<div class="health-empty">SSH gateway details are unavailable for this launch.</div>';
    return;
  }

  passwordDisplay = sshGatewayPasswordVisible ? gatewayPassword : getMaskedSshGatewayPassword(gatewayPassword);
  toggleLabel = sshGatewayPasswordVisible ? 'Hide' : 'View';
  container.classList.add('is-populated');

  container.innerHTML =
    '<div class="mlhub-card-header">' +
      '<div>' +
        '<h3 class="mlhub-card-title">SSH gateway</h3>' +
        '<p class="mlhub-card-copy">Use these credentials to reach the machine hosting your notebook over SSH after the launch completes.</p>' +
      '</div>' +
    '</div>' +
    '<div class="session-options is-enabled ssh-gateway-panel">' +
      '<div class="ssh-gateway-row">' +
        '<div class="ssh-gateway-row-copy">' +
          '<span class="share-toggle-title">Gateway endpoint</span>' +
          '<span class="share-toggle-copy">Connect to the SSH gateway below once your notebook machine is running.</span>' +
        '</div>' +
        '<div class="ssh-gateway-value-block">' + escapeHtml(gatewayHost) + ':' + escapeHtml(String(gatewayPort)) + '</div>' +
      '</div>' +
      '<div class="ssh-gateway-row">' +
        '<div class="ssh-gateway-row-copy">' +
          '<span class="share-toggle-title">Username</span>' +
          '<span class="share-toggle-copy">Use your generated safe username when connecting through the gateway.</span>' +
        '</div>' +
        '<div class="ssh-gateway-value-block">' + escapeHtml(gatewayUsername) + '</div>' +
      '</div>' +
      '<div class="ssh-gateway-row is-password">' +
        '<div class="ssh-gateway-row-copy">' +
          '<span class="share-toggle-title">Password</span>' +
          '<span class="share-toggle-copy">A fresh password is generated every time this form loads. The one submitted with this launch becomes active.</span>' +
        '</div>' +
        '<div class="ssh-gateway-password-row">' +
          '<div class="ssh-gateway-password-box">' + escapeHtml(passwordDisplay) + '</div>' +
          '<button type="button" class="ssh-gateway-toggle" data-ssh-password-toggle="true">' + escapeHtml(toggleLabel) + '</button>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="session-note is-muted ssh-gateway-note"><strong>Note:</strong> This SSH gateway forwards you to the machine selected for this notebook launch. External connections to this gateway might require a VPN. See the <a href="' + vpnGuideUrl + '" target="_blank" rel="noreferrer">WireGuard setup guide</a>.</div>';

  Array.prototype.forEach.call(container.querySelectorAll('[data-ssh-password-toggle]'), function(button) {
    button.addEventListener('click', function() {
      sshGatewayPasswordVisible = !sshGatewayPasswordVisible;
      renderSshGatewayCard();
    });
  });
}

function buildNodeHistoryMetricOptions(machineInstance) {
  var selectedMetric = getSelectedHistoryMetric(machineInstance.instance_id);
  var metricOptions = [
    { value: 'fitness', label: 'Fitness history' },
    { value: 'cpu', label: 'CPU usage history' },
    { value: 'vram', label: 'VRAM usage history' },
    { value: 'assigned', label: 'People assigned history' }
  ];

  return metricOptions.map(function(metricOption) {
    return '<option value="' + escapeHtml(metricOption.value) + '"' + (selectedMetric === metricOption.value ? ' selected' : '') + '>' + escapeHtml(metricOption.label) + '</option>';
  }).join('');
}

function buildNodeHistoryMarkup(machineInstance) {
  return '' +
    '<div class="node-history-panel" data-instance-id="' + escapeHtml(machineInstance.instance_id) + '">' +
      '<div class="node-history-toolbar">' +
        '<div>' +
          '<div class="node-history-title">History</div>' +
          '<div class="node-history-copy">Pick a metric to plot up to 16 sampled points from the retained node history.</div>' +
        '</div>' +
        '<label class="node-history-control">' +
          '<span class="node-history-control-label">Metric</span>' +
          '<select class="node-history-select">' + buildNodeHistoryMetricOptions(machineInstance) + '</select>' +
        '</label>' +
      '</div>' +
      '<div class="node-history-summary"></div>' +
      '<div class="node-history-plot"></div>' +
    '</div>';
}

function buildNodeDetails(machine, snapshot, machineInstance) {
  var historyMarkup = buildNodeHistoryMarkup(machineInstance);
  var assignmentsMarkup = buildAssignmentsTableMarkup(machineInstance);
  if (!snapshot) {
    return '' +
      '<div class="health-empty">This node is offline or has not reported telemetry yet.</div>' +
      historyMarkup +
      assignmentsMarkup;
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
      historyMarkup +
      assignmentsMarkup +
      errorMarkup;
}

function renderMachineHealthTable(machine) {
  var tableContainer = document.getElementById('machineHealthTable');
  var visibleMachineInstances;
  var recommendedMachineInstance;
  destroyNodeHistoryPlots();

  if (!machine || getMachineInstances(machine).length === 0) {
    tableContainer.innerHTML = '<div class="health-empty">No machine instances available for this profile.</div>';
    return;
  }

  visibleMachineInstances = getVisibleMachineInstances(machine);
  recommendedMachineInstance = visibleMachineInstances[0] || null;

  if (visibleMachineInstances.length === 0) {
    tableContainer.innerHTML = '<div class="health-empty">' + escapeHtml(
      getSharedAccessRequested(machine)
        ? 'No nodes are currently listed for this machine profile.'
        : 'No zero-assignment nodes are currently available to request exclusive access.'
    ) + '</div>';
    return;
  }

  if (expandedHealthInstanceId && !visibleMachineInstances.some(function(instance) { return instance.instance_id === expandedHealthInstanceId; })) {
    expandedHealthInstanceId = null;
  }

  tableContainer.innerHTML =
    '<div class="health-list">' +
    visibleMachineInstances.map(function(machineInstance) {
      var snapshot = nodeHealth[machineInstance.instance_id];
      var offline = isOfflineSnapshot(snapshot);
      var score = !offline ? Number(snapshot.fitness_score) : null;
      var scoreText = score !== null ? Math.round(score) : 'OFFLINE';
      var barWidth = score !== null ? Math.max(8, Math.min(100, score)) : 8;
      var color = getHealthColor(snapshot);
      var statusMeta = getStatusMeta(snapshot);
      var scoreLabel = offline ? 'Status' : 'Fitness';
      var scoreStatusMarkup = offline
        ? ''
        : '<span class="health-status-pill ' + escapeHtml(statusMeta.className) + '">' + escapeHtml(statusMeta.label) + '</span>';
      var isRecommended = !!(recommendedMachineInstance && recommendedMachineInstance.instance_id === machineInstance.instance_id);
      var isOpen = expandedHealthInstanceId === machineInstance.instance_id;
      var isSelected = selectedMachineInstanceId === machineInstance.instance_id;
      var subtitle = escapeHtml(formatAssignedUserCount(machineInstance)) + ' · ' + escapeHtml(
        isSelected
          ? 'Launch target'
          : 'Open details to inspect usage and history'
      );

      return '' +
        '<div class="health-item ' + (isOpen ? 'is-open' : '') + (isSelected ? ' is-selected-for-launch' : '') + '">' +
          '<div class="health-trigger-row">' +
            '<button type="button" class="health-trigger" data-instance-id="' + escapeHtml(machineInstance.instance_id) + '">' +
              '<div class="health-main">' +
                '<div class="health-host-line">' +
                  '<div class="health-host' + (isSelected ? ' is-selected' : '') + '">' + escapeHtml(displayHostname(machineInstance)) + '</div>' +
                  '<div class="health-host-badges">' + buildNodeHeaderBadges(machine, machineInstance, isRecommended) + '</div>' +
                '</div>' +
                '<div class="health-subtitle">' + subtitle + '</div>' +
                '<div class="health-bar"><div class="health-bar-fill" style="width:' + escapeHtml(barWidth) + '%; background:' + escapeHtml(color) + ';"></div></div>' +
              '</div>' +
            '</button>' +
            '<div class="health-side">' +
              '<div class="health-score-card" style="' + escapeHtml(buildHealthScoreCardStyle(score)) + '">' +
                '<div class="health-score-label">' + escapeHtml(scoreLabel) + '</div>' +
                '<div class="health-score-value' + (offline ? ' is-text' : '') + '">' + escapeHtml(scoreText) + '</div>' +
                scoreStatusMarkup +
              '</div>' +
              '<button type="button" class="health-detail-toggle' + (isOpen ? ' is-open' : '') + '" data-instance-id="' + escapeHtml(machineInstance.instance_id) + '" aria-expanded="' + (isOpen ? 'true' : 'false') + '">' +
                (isOpen ? 'Hide details' : 'View details') +
              '</button>' +
            '</div>' +
          '</div>' +
          '<div class="health-detail">' + buildNodeDetails(machine, snapshot, machineInstance) + '</div>' +
        '</div>';
    }).join('') +
    '</div>';

  Array.prototype.forEach.call(tableContainer.querySelectorAll('.health-trigger'), function(button) {
    button.addEventListener('click', function() {
      var instanceId = button.getAttribute('data-instance-id');
      expandedHealthInstanceId = null;
      setSelectedMachineInstance(instanceId);
      renderSelectedMachine();
    });
  });

  Array.prototype.forEach.call(tableContainer.querySelectorAll('.health-detail-toggle'), function(button) {
    button.addEventListener('click', function() {
      var instanceId = button.getAttribute('data-instance-id');
      setSelectedMachineInstance(instanceId);
      expandedHealthInstanceId = expandedHealthInstanceId === instanceId ? null : instanceId;
      renderSelectedMachine();
    });
  });

  Array.prototype.forEach.call(tableContainer.querySelectorAll('.node-history-panel'), function(panel) {
    var metricSelect = panel.querySelector('.node-history-select');
    if (!metricSelect) {
      return;
    }

    metricSelect.addEventListener('change', function() {
      setSelectedHistoryMetric(panel.getAttribute('data-instance-id'), metricSelect.value);
      renderNodeHistoryPanel(panel);
    });

    renderNodeHistoryPanel(panel);
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
  syncSelectedMachineInstance(machine);
  renderSshGatewayCard();
  renderMachineCards();
  renderMachineDetails(machine);
  renderLaunchSummaryCard(machine);
  renderMachineHealthTable(machine);
}

function setSelectedMachine(index) {
  if (filteredMachinesList.length === 0) {
    return;
  }
  setSelectedMachineInstance(null);
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

function revealSelectableNode(machine) {
  var visibleMachineInstances = getVisibleMachineInstances(machine);
  if (!visibleMachineInstances.length) {
    return;
  }

  if (!expandedHealthInstanceId) {
    expandedHealthInstanceId = visibleMachineInstances[0].instance_id;
  }
}

function initializeMachineForm() {
  var hostForm;
  populateMachineOptions();
  renderSshGatewayCard();

  hostForm = document.getElementById('machineSelect').form;
  if (hostForm) {
    Array.prototype.forEach.call(hostForm.querySelectorAll('button[type="submit"], input[type="submit"]'), function(button) {
      button.classList.add('mlhub-submit-button');
    });

    hostForm.addEventListener('submit', function(event) {
      if (selectedMachineInstanceId) {
        return;
      }

      revealSelectableNode(getCurrentMachine());
      renderSelectedMachine();
      event.preventDefault();

      var nodeHealthCard = document.querySelector('.node-health-card');
      if (nodeHealthCard) {
        nodeHealthCard.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    });
  }
}

initializeMachineForm();
