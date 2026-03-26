var formPayload = {formPayload};
var machines = formPayload.machines || [];
var nodeHealth = formPayload.nodeHealth || {};
var uiContext = formPayload.uiContext || {};
var nodeHealthHistory = formPayload.nodeHealthHistory || {};
var sshGatewayContext = uiContext.sshGateway || {};
var filteredMachinesList = machines;
var selectedMachineIndex = 0;
var expandedHealthInstanceId = null;
var preferredSharedAccessRequested = true;
var userCanRequestExclusive = !!uiContext.canRequestExclusive;
var selectedMachineInstanceId = null;
var selectedHistoryMetricByInstanceId = {};
var sshGatewayPasswordVisible = false;

function escapeHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function displayHostname(machineInstance) {
  if (!machineInstance) {
    return 'unknown';
  }
  return machineInstance.hostname || machineInstance.endpoint || machineInstance.instance_id;
}

function bytesToGiB(bytesValue) {
  if (bytesValue === null || bytesValue === undefined) {
    return 'n/a';
  }
  return (bytesValue / Math.pow(1024, 3)).toFixed(2) + ' GiB';
}

function bytesToGiBNumeric(bytesValue) {
  if (bytesValue === null || bytesValue === undefined) {
    return null;
  }
  return bytesValue / Math.pow(1024, 3);
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return 'n/a';
  }
  return Number(value).toFixed(1) + '%';
}

function getHealthColorFromScore(score) {
  if (score === null || score === undefined || isNaN(Number(score))) {
    return '#8d97a6';
  }
  var hue = Math.max(0, Math.min(120, (Number(score) / 100) * 120));
  return 'hsl(' + hue + ', 75%, 45%)';
}

function getHealthColor(snapshot) {
  if (!snapshot || snapshot.fitness_score === null || snapshot.fitness_score === undefined || !snapshot.healthy || snapshot.stale) {
    return '#8d97a6';
  }
  return getHealthColorFromScore(snapshot.fitness_score);
}

function interpolateNumber(startValue, endValue, ratio) {
  return Math.round(startValue + (endValue - startValue) * ratio);
}

function getFitnessColorChannels(score) {
  var red = [248, 113, 113];
  var orange = [255, 122, 26];
  var green = [56, 193, 114];
  var clampedScore;
  var startColor;
  var endColor;
  var ratio;

  if (score === null || score === undefined || isNaN(Number(score))) {
    return [141, 151, 166];
  }

  clampedScore = Math.max(0, Math.min(100, Number(score)));
  if (clampedScore <= 50) {
    startColor = red;
    endColor = orange;
    ratio = clampedScore / 50;
  } else {
    startColor = orange;
    endColor = green;
    ratio = (clampedScore - 50) / 50;
  }

  return [
    interpolateNumber(startColor[0], endColor[0], ratio),
    interpolateNumber(startColor[1], endColor[1], ratio),
    interpolateNumber(startColor[2], endColor[2], ratio),
  ];
}

function getRgbaString(colorChannels, alpha) {
  return 'rgba(' + colorChannels[0] + ', ' + colorChannels[1] + ', ' + colorChannels[2] + ', ' + alpha + ')';
}

function isOfflineSnapshot(snapshot) {
  return !snapshot || snapshot.stale || !snapshot.healthy || snapshot.fitness_score === null || snapshot.fitness_score === undefined;
}

function getStatusMeta(snapshot) {
  if (isOfflineSnapshot(snapshot)) {
    return { label: 'OFFLINE', className: 'is-stale' };
  }
  return { label: 'Healthy', className: 'is-healthy' };
}

function getMachineInstances(machine) {
  return Array.isArray(machine && machine.instances) ? machine.instances : [];
}

function getMachineHealthStats(machine) {
  var stats = {
    healthy: 0,
    stale: 0,
    issues: 0,
    noData: 0,
    bestScore: null,
    reportingNodes: 0
  };

  getMachineInstances(machine).forEach(function(machineInstance) {
    var snapshot = nodeHealth[machineInstance.instance_id];
    if (!snapshot) {
      stats.noData += 1;
      return;
    }

    if (snapshot.stale) {
      stats.stale += 1;
    } else if (!snapshot.healthy) {
      stats.issues += 1;
    } else {
      stats.healthy += 1;
    }

    if (snapshot.fitness_score !== null && snapshot.fitness_score !== undefined) {
      stats.reportingNodes += 1;
      if (stats.bestScore === null || Number(snapshot.fitness_score) > stats.bestScore) {
        stats.bestScore = Number(snapshot.fitness_score);
      }
    }
  });

  return stats;
}

function getMachineGpuText(machine) {
  if (!Array.isArray(machine.gpu) || machine.gpu.length === 0) {
    return 'Unavailable';
  }
  return machine.gpu.join(', ');
}

function getMachineCpuText(machine) {
  if (!machine.cpu_cores) {
    return machine.cpu_model || 'Unavailable';
  }
  return machine.cpu_cores + ' cores';
}

function getMachineRamText(machine) {
  if (!machine.ram) {
    return 'Unavailable';
  }
  return machine.ram + ' GB';
}

function machineSupportsSharing(machine) {
  return !!(machine && machine.shared_access_enabled);
}

function isSharingForced(machine) {
  return machineSupportsSharing(machine) && !userCanRequestExclusive;
}

function getSharedAccessRequested(machine) {
  if (!machineSupportsSharing(machine)) {
    return false;
  }
  if (isSharingForced(machine)) {
    return true;
  }
  return preferredSharedAccessRequested;
}

function getCurrentMachine() {
  return filteredMachinesList[selectedMachineIndex] || null;
}

function getSelectedMachineInstance(machine) {
  if (!machine || !selectedMachineInstanceId) {
    return null;
  }

  return getMachineInstances(machine).find(function(machineInstance) {
    return machineInstance.instance_id === selectedMachineInstanceId;
  }) || null;
}

function shouldDisplayMachineInstance(machine, machineInstance) {
  if (!machine || !machineInstance) {
    return false;
  }

  if (!getSharedAccessRequested(machine)) {
    return Number(machineInstance.assigned_user_count || 0) === 0;
  }

  return true;
}

function getVisibleMachineInstances(machine) {
  return getMachineInstances(machine).filter(function(machineInstance) {
    return shouldDisplayMachineInstance(machine, machineInstance);
  }).sort(function(firstInstance, secondInstance) {
    var firstSnapshot = nodeHealth[firstInstance.instance_id];
    var secondSnapshot = nodeHealth[secondInstance.instance_id];
    var firstFitness = firstSnapshot && firstSnapshot.fitness_score !== null && firstSnapshot.fitness_score !== undefined
      ? Number(firstSnapshot.fitness_score)
      : -1;
    var secondFitness = secondSnapshot && secondSnapshot.fitness_score !== null && secondSnapshot.fitness_score !== undefined
      ? Number(secondSnapshot.fitness_score)
      : -1;

    if (firstFitness !== secondFitness) {
      return secondFitness - firstFitness;
    }

    return displayHostname(firstInstance).localeCompare(displayHostname(secondInstance));
  });
}

function syncSelectedMachineInstance(machine) {
  var visibleMachineInstances;
  if (!machine) {
    selectedMachineInstanceId = null;
    expandedHealthInstanceId = null;
    return;
  }

  visibleMachineInstances = getVisibleMachineInstances(machine);
  if (!visibleMachineInstances.length) {
    selectedMachineInstanceId = null;
    expandedHealthInstanceId = null;
    return;
  }

  if (!visibleMachineInstances.some(function(machineInstance) {
    return machineInstance.instance_id === selectedMachineInstanceId;
  })) {
    selectedMachineInstanceId = null;
  }

  if (expandedHealthInstanceId && !visibleMachineInstances.some(function(machineInstance) {
    return machineInstance.instance_id === expandedHealthInstanceId;
  })) {
    expandedHealthInstanceId = null;
  }

  if (!selectedMachineInstanceId && visibleMachineInstances[0]) {
    selectedMachineInstanceId = visibleMachineInstances[0].instance_id;
  }
}

function setSelectedMachineInstance(instanceId) {
  selectedMachineInstanceId = instanceId || null;
}

function isMachineInstancePotentiallyUnavailable(machine, machineInstance) {
  var snapshot = nodeHealth[machineInstance.instance_id];
  var offline = isOfflineSnapshot(snapshot);

  if (!getSharedAccessRequested(machine)) {
    return offline;
  }

  return offline || !!machineInstance.has_exclusive_allocation;
}

function getSelectedHistoryMetric(instanceId) {
  if (!selectedHistoryMetricByInstanceId[instanceId]) {
    selectedHistoryMetricByInstanceId[instanceId] = 'fitness';
  }
  return selectedHistoryMetricByInstanceId[instanceId];
}

function setSelectedHistoryMetric(instanceId, metricKey) {
  selectedHistoryMetricByInstanceId[instanceId] = metricKey;
}
