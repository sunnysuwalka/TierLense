$ErrorActionPreference = 'Stop'

# Run this script from the TierLense repository root, with the API and worker running.
# It never reads, prints, or changes .env credentials.
$BaseUri = 'http://127.0.0.1:8000/api/v1'

Write-Host 'Checking TierLense API readiness...' -ForegroundColor Cyan
$ready = Invoke-RestMethod -Method Get -Uri "$BaseUri/health/ready"
$ready | ConvertTo-Json -Depth 6 | Write-Host

$testOrganizationName = 'NVIDIA Corporation - Sprint 2 Live Validation'
$payload = @{
    name = $testOrganizationName
    website = 'https://www.nvidia.com'
    country_code = 'US'
    description = 'Positive-control test using the real public company NVIDIA Corporation to validate TierLense Sprint 2 live discovery, public-document retrieval, evidence-backed extraction, identity checks, and persistent results. The test label is administrative; the underlying organization is NVIDIA Corporation.'
    watch_profile = @{
        dependency_role = 'focal company'
        products_services = @(
            'data-center GPUs and AI accelerators',
            'accelerated computing platforms',
            'semiconductor designs',
            'networking and interconnect systems',
            'CUDA software platform'
        )
        dependency_context = 'Positive-control assessment of public evidence about NVIDIA Corporation. Look for official disclosures concerning manufacturing, wafer fabrication, memory, advanced packaging, testing, assembly, suppliers, supply capacity, geographic dependencies, and reported operational or regulatory disruptions. Treat NVIDIA as the focal company, not as a supplier to an assumed customer. Do not infer supplier relationships, disruptions, ownership, or risk levels without explicit source support.'
        criticality = 'high'
        identity_clues = @('NVIDIA Corporation', 'NVIDIA', 'NVDA')
    }
}

$payloadJson = $payload | ConvertTo-Json -Depth 8
$searchTerm = [System.Uri]::EscapeDataString($testOrganizationName)
$existingResponse = Invoke-RestMethod -Method Get -Uri "$BaseUri/organizations?q=$searchTerm&limit=50"
$existingOrganization = @($existingResponse.items | Where-Object { $_.name -eq $testOrganizationName } | Select-Object -First 1)

if ($existingOrganization.Count -gt 0) {
    # Make re-runs repeatable: refresh only this dedicated test profile and queue a new manual scan.
    $organizationId = [string]$existingOrganization[0].id
    $profileJson = $payload.watch_profile | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Put -Uri "$BaseUri/organizations/$organizationId/watch-profile" -ContentType 'application/json' -Body $profileJson | Out-Null
    $manualJobJson = (@{ job_type = 'manual_scan' } | ConvertTo-Json -Depth 4)
    $job = Invoke-RestMethod -Method Post -Uri "$BaseUri/organizations/$organizationId/investigation-jobs" -ContentType 'application/json' -Body $manualJobJson
    $jobId = [string]$job.id
    Write-Host "Found the existing dedicated test organization; queued a fresh manual scan."
} else {
    Write-Host "`nCreating the NVIDIA positive-control organization and initial investigation..." -ForegroundColor Cyan
    $onboard = Invoke-RestMethod -Method Post -Uri "$BaseUri/organizations" -ContentType 'application/json' -Body $payloadJson
    $organizationId = [string]$onboard.organization.id
    $jobId = [string]$onboard.initial_investigation.id
    Write-Host ("API notice:      {0}" -f $onboard.notice)
}
Write-Host ("Organization ID: {0}" -f $organizationId)
Write-Host ("Job ID:          {0}" -f $jobId)
Write-Host "`nWaiting for the PostgreSQL-backed worker to finish (up to 10 minutes)..." -ForegroundColor Cyan

$pipelineStatus = $null
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    $pipelineStatus = Invoke-RestMethod -Method Get -Uri "$BaseUri/investigation-jobs/$jobId/pipeline-status"
    $message = [string]$pipelineStatus.progress_message
    Write-Host ("[{0,3}/120] status={1}; progress={2}%; {3}" -f ($attempt + 1), $pipelineStatus.status, $pipelineStatus.progress_percent, $message)
    if ($pipelineStatus.status -in @('completed', 'failed')) {
        break
    }
    Start-Sleep -Seconds 5
}

Write-Host "`n=== FINAL PIPELINE STATUS ===" -ForegroundColor Cyan
$pipelineStatus | ConvertTo-Json -Depth 10 | Write-Host

Write-Host "`n=== DISCOVERED SOURCES ===" -ForegroundColor Cyan
$sourcesResponse = Invoke-RestMethod -Method Get -Uri "$BaseUri/investigation-jobs/$jobId/sources?limit=100"
if ($sourcesResponse.items.Count -gt 0) {
    $sourcesResponse.items |
        Select-Object `
            @{Name='Title'; Expression={$_.title}},
            @{Name='URL'; Expression={$_.url}},
            @{Name='Domain'; Expression={$_.domain}},
            @{Name='Relevant'; Expression={$_.relevant}},
            @{Name='Score'; Expression={$_.relevance_score}},
            @{Name='RelevanceReason'; Expression={$_.relevance_reason}},
            @{Name='FetchStatus'; Expression={$_.fetch_status}},
            @{Name='HasEvidenceDocument'; Expression={[bool]$_.evidence_document_id}},
            @{Name='Error'; Expression={$_.error_summary}} |
        Format-Table -AutoSize -Wrap
} else {
    Write-Host 'No sources returned for this job.'
}

Write-Host "`n=== EXTRACTED FINDINGS ===" -ForegroundColor Cyan
$findingsResponse = Invoke-RestMethod -Method Get -Uri "$BaseUri/investigation-jobs/$jobId/findings?limit=100"
if ($findingsResponse.items.Count -gt 0) {
    $findingsResponse.items |
        Select-Object finding_type, subject_name, predicate, object_value, validation_status, model_confidence, summary, source_passage |
        Format-List
    Write-Host 'Finding counts by evidence-validation status:'
    $findingsResponse.items |
        Group-Object validation_status |
        Select-Object Name, Count |
        Format-Table -AutoSize
} else {
    Write-Host 'No findings returned for this job.'
}

# Save the API results locally so the run can be assessed without sharing secrets.
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$reportPath = Join-Path (Get-Location) "tierlense_s2_live_test_nvidia_$stamp.json"
$report = [ordered]@{
    test = 'Sprint 2 live positive-control validation'
    company = 'NVIDIA Corporation'
    organization_id = $organizationId
    job_id = $jobId
    pipeline_status = $pipelineStatus
    sources = $sourcesResponse.items
    findings = $findingsResponse.items
    exported_at = [DateTimeOffset]::Now.ToString('o')
}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$documentCount = @($sourcesResponse.items | Where-Object { $_.evidence_document_id }).Count
$relevantCount = @($sourcesResponse.items | Where-Object { $_.relevant -eq $true }).Count
$verifiedCount = @($findingsResponse.items | Where-Object { $_.validation_status -eq 'passage_verified' }).Count
Write-Host "`n=== ACCEPTANCE CHECK ===" -ForegroundColor Cyan
Write-Host ("Job completed:             {0}" -f ($pipelineStatus.status -eq 'completed'))
Write-Host ("Sources discovered:        {0}" -f $sourcesResponse.total)
Write-Host ("Sources classified relevant: {0}" -f $relevantCount)
Write-Host ("Sources with saved docs:   {0}" -f $documentCount)
Write-Host ("Findings extracted:        {0}" -f $findingsResponse.total)
Write-Host ("Passage-verified findings: {0}" -f $verifiedCount)
Write-Host ("Report saved to:           {0}" -f $reportPath)

if ($pipelineStatus.status -ne 'completed') {
    Write-Warning 'The job did not reach completed status within the polling window or it failed. Include the final pipeline status and report in the assessment.'
} elseif ($documentCount -gt 0 -and $verifiedCount -gt 0) {
    Write-Host 'POSITIVE CONTROL: end-to-end source retrieval and passage-verified extraction observed.' -ForegroundColor Green
} else {
    Write-Warning 'The job completed, but the full positive-control path was not demonstrated. Zero findings is not automatically a failure; assess the source and identity/fetch statuses in the report.'
}
