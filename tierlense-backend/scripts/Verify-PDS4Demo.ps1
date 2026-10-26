$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000/api/v1"
$demoName = "PDS-4 Demo - Army Logistics Spares (SIMULATED)"
$escapedName = [System.Uri]::EscapeDataString($demoName)

$orgResponse = Invoke-RestMethod -Method Get -Uri "$base/organizations?q=$escapedName&limit=20"
$org = $orgResponse.items | Where-Object { $_.name -eq $demoName } | Select-Object -First 1
if (-not $org) { throw "Demo organization not found. Register it once through the frontend with the exact configured name." }
$orgId = $org.id

$entities = Invoke-RestMethod "$base/supply-chain/organizations/$orgId/entities?limit=200"
$relationships = Invoke-RestMethod "$base/supply-chain/organizations/$orgId/relationships?limit=200"
$graph = Invoke-RestMethod "$base/supply-chain/organizations/$orgId/graph?direction=both&max_depth=4"
$disruptions = Invoke-RestMethod "$base/supply-chain/organizations/$orgId/disruptions?limit=100"
$jobs = Invoke-RestMethod "$base/organizations/$orgId/investigation-jobs?limit=10"
$schedule = Invoke-RestMethod "$base/organizations/$orgId/scan-schedule"
$history = Invoke-RestMethod "$base/organizations/$orgId/history?limit=10"
$changes = Invoke-RestMethod "$base/organizations/$orgId/evidence-changes"
$alternatives = Invoke-RestMethod "$base/organizations/$orgId/alternative-supplier-recommendations?limit=20"

$job = $jobs.items | Where-Object { $_.id -eq $schedule.last_job_id } | Select-Object -First 1
if (-not $job) { $job = $jobs.items | Sort-Object created_at -Descending | Select-Object -First 1 }
$names = @($graph.nodes | ForEach-Object { $_.entity.name })
# Use the risk assessments already captured in the historical snapshot.
# The separate /likelihood GET endpoint appends a new assessment, so this verifier
# deliberately avoids it to remain read-only.
$risk = $null
if ($history.items.Count -gt 0 -and $history.items[0].graph_snapshot.risk_assessments) {
    $risk = $history.items[0].graph_snapshot.risk_assessments | Select-Object -First 1
}

$result = [PSCustomObject]@{
    Organization = $org.name
    OrganizationId = $orgId
    JobStatus = $job.status
    ExternalModelCalls = $job.result_summary.external_model_calls
    RegistryEntities = $entities.total
    RegistryRelationships = $relationships.total
    GraphNodesAtDepth4 = $graph.nodes.Count
    GraphRelationshipsAtDepth4 = $graph.relationships.Count
    HasTier4Supplier = (@($names | Where-Object { $_ -like "*Western Polymer Feedstock*" -or $_ -like "*Shinano Specialty Resin*" }).Count -gt 0)
    DisruptionEvents = $disruptions.total
    RiskBandExample = if ($risk) { $risk.band } else { "none" }
    RiskIndexIsUncalibrated = if ($risk) { -not $risk.is_calibrated } else { $false }
    HistoricalSnapshots = $history.total
    EvidenceChanges = @($changes).Count
    AlternativeRecommendations = $alternatives.total
    CandidatesAcrossRecommendations = (($alternatives.items | ForEach-Object { @($_.candidates).Count } | Measure-Object -Sum).Sum)
    ScheduleLastJobMatches = ($schedule.last_job_id -eq $job.id)
}
$result | Format-List

if ($job.status -ne "completed") { throw "FAIL: demo job is not completed." }
if ($job.result_summary.external_model_calls -ne 0) { throw "FAIL: expected zero external model calls for the local demo job." }
if ($entities.total -lt 20 -or $relationships.total -lt 20) { throw "FAIL: expected the full demo graph registry." }
if ($graph.nodes.Count -lt 15 -or -not $result.HasTier4Supplier) { throw "FAIL: multi-tier graph did not expose the tier-4 test node." }
if ($disruptions.total -lt 3 -or $history.total -lt 1 -or @($changes).Count -lt 1) { throw "FAIL: disruption/history/change records are missing." }
if ($alternatives.total -lt 2 -or $result.CandidatesAcrossRecommendations -lt 2) { throw "FAIL: alternative supplier candidates are missing." }
if (-not $result.RiskIndexIsUncalibrated) { throw "FAIL: risk score should remain explicitly uncalibrated." }
Write-Host "PASS: PDS-4 synthetic demo is populated across graph, disruptions, alternatives and history." -ForegroundColor Green
