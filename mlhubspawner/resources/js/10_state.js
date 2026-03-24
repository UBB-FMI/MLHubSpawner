var formPayload = {formPayload};
var machines = formPayload.machines || [];
var nodeHealth = formPayload.nodeHealth || {};
var uiContext = formPayload.uiContext || {};
var nodeHealthHistory = formPayload.nodeHealthHistory || {};
var filteredMachinesList = machines;
var selectedMachineIndex = 0;
var expandedHealthInstanceId = null;
var preferredSharedAccessRequested = true;
var userCanRequestExclusive = !!uiContext.canRequestExclusive;
var selectedHistoryMetricByInstanceId = {};

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

function getSelectedHistoryMetric(instanceId) {
  if (!selectedHistoryMetricByInstanceId[instanceId]) {
    selectedHistoryMetricByInstanceId[instanceId] = 'fitness';
  }
  return selectedHistoryMetricByInstanceId[instanceId];
}

function setSelectedHistoryMetric(instanceId, metricKey) {
  selectedHistoryMetricByInstanceId[instanceId] = metricKey;
}
