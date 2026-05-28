let savedQueries = [];
let currentUserId = null; // Will be set from template or API
let referenceRequestInFlight = false;

function showNotification(message, type = 'info') {
    let notification = document.getElementById('notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'notification';
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 5px;
            color: white;
            font-weight: bold;
            z-index: 1000;
            max-width: 300px;
            word-wrap: break-word;
        `;
        document.body.appendChild(notification);
    }

    notification.textContent = message;
    switch(type) {
        case 'success':
            notification.style.backgroundColor = '#4CAF50';
            break;
        case 'error':
            notification.style.backgroundColor = '#f44336';
            break;
        case 'warning':
            notification.style.backgroundColor = '#ff9800';
            break;
        default:
            notification.style.backgroundColor = '#2196F3';
    }

    notification.style.display = 'block';
    setTimeout(() => {
        notification.style.display = 'none';
    }, 3000);
}

async function loadSavedQueries() {
    try {
        const response = await fetch('/api/queries');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        savedQueries = data.queries || [];
        console.log('Loaded savedQueries:', savedQueries);
        populateQuerySelect();
    } catch (err) {
        console.error('Error loading queries:', err);
        showNotification('Could not load queries from server', 'warning');
    }
}

function populateQuerySelect() {
    const select = document.getElementById('docQuerySelect');
    if (!select) {
        console.error('docQuerySelect element not found');
        return;
    }
    
    console.log('Populating select with queries:', savedQueries);
    select.innerHTML = '<option value="">Select a query...</option>';
    
    if (!savedQueries || savedQueries.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No queries available - please add a query first';
        option.disabled = true;
        select.appendChild(option);
        return;
    }
    
    savedQueries.forEach(query => {
        const option = document.createElement('option');
        option.value = query.id;
        option.textContent = query.title || query.query || `Query ${query.id}`;
        select.appendChild(option);
    });
}

function uploadDocument() {
    let name = document.getElementById("docName").value.trim();
    let fileInput = document.getElementById("docFile");
    let file = fileInput.files[0];

    if (!name || !file) {
        showNotification("Please provide a document name and select a file.", 'warning');
        return;
    }

    // Show loading state
    const uploadBtn = document.getElementById('uploadDocumentBtn');
    const originalText = uploadBtn ? uploadBtn.innerHTML : '';
    if (uploadBtn) {
        uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
        uploadBtn.disabled = true;
    }

    let reader = new FileReader();
    reader.onload = function(e) {
        let base64Data = e.target.result.split(",")[1];

        fetch("/document/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: name,
                file: base64Data,
                mime_type: file.type,
                user_id: currentUserId || "{{ user.id }}" // Jinja fallback
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                showNotification("Document uploaded successfully!", 'success');
                // Clear form
                document.getElementById("docName").value = '';
                document.getElementById("docFile").value = '';
                document.getElementById("fileName").textContent = 'Choose file…';
                // Reload page to show new document
                setTimeout(() => location.reload(), 1000);
            } else {
                showNotification(data.error || "Error uploading document.", 'error');
            }
        })
        .catch(err => {
            console.error(err);
            showNotification("Error uploading document.", 'error');
        })
        .finally(() => {
            if (uploadBtn) {
                uploadBtn.innerHTML = originalText;
                uploadBtn.disabled = false;
            }
        });
    };
    reader.readAsDataURL(file);
}


async function scanDocument(docId) {
    const scanBtn = document.getElementById(`scan-btn-${docId}`);
    const originalHtml = scanBtn ? scanBtn.innerHTML : '';

    try {
        // Show loading state
        if (scanBtn) {
            scanBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Scanning...';
            scanBtn.disabled = true;
        }

        const response = await fetch(`/document/scan/${docId}`, { method: "POST" });
        const data = await response.json();

        if (!response.ok || data.error) {
            showNotification("Error: " + data.error, 'error');
            return;
        }

        // Update the document display with enhanced results
        const docItem = document.getElementById("doc-" + docId);
        if (docItem && data.result) {
            const statusEl = docItem.querySelector(".doc-status");
            if (statusEl) {
                const result = data.result;
                let validityClass = '';
                switch(result.overall_validity) {
                    case 'valid': validityClass = 'validity-valid'; break;
                    case 'invalid': validityClass = 'validity-invalid'; break;
                    case 'questionable': validityClass = 'validity-questionable'; break;
                }

                statusEl.innerHTML = `
                    <small>Status: <strong>completed</strong></small><br>
                    <div class="scan-details ${validityClass}">
                        <strong>Validity: ${result.overall_validity || 'Unknown'}</strong>
                        ${result.authenticity_score ? `<br><small>Authenticity Score: ${result.authenticity_score}%</small>` : ''}
                        ${result.required_elements_check ? `
                            <br><small>Elements Check: 
                                ${result.required_elements_check.all_present ? 
                                    'All Present ✓' : 
                                    `Missing: ${(result.required_elements_check.missing_elements || []).join(', ')}`
                                }
                            </small>
                        ` : ''}
                    </div>
                `;
            }

            // scanBtn.textContent = 'Re-scan';
        }

        showNotification("Scan completed successfully!", 'success');
        if (scanBtn) {
            scanBtn.innerHTML = '<i class="fas fa-search"></i> Re-scan';
        }
        
        // Update user compliance score
        await updateUserComplianceDisplay();

    } catch (err) {
        console.error("Scan error:", err);
        showNotification("An error occurred while scanning", 'error');
    } finally {
        // Reset button state
        if (scanBtn) {
            scanBtn.disabled = false;
            if (scanBtn.innerHTML.includes('Scanning') && originalHtml) {
                scanBtn.innerHTML = originalHtml;
            }
        }
    }
}

function deleteDocument(id) {
    if (!confirm("Are you sure you want to delete this document?")) return;

    fetch(`/document/delete/${id}`, { method: "DELETE" })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success' || data.message) {
            showNotification("Document deleted successfully!", 'success');
            document.getElementById("doc-" + id).remove();
            updateUserComplianceDisplay();
        } else {
            showNotification(data.error || "Error deleting document.", 'error');
        }
    })
    .catch(err => {
        console.error(err);
        showNotification("Error deleting document.", 'error');
    });
}

function renderDocsEnhanced(documents) {
    const container = document.getElementById('required-docs-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (!documents || documents.length === 0) {
        container.innerHTML = '<p>No required documents yet. Run "Analyze" or click "Get required Documents".</p>';
        return;
    }
    
    documents.forEach(doc => {
        const docDiv = document.createElement('div');
        docDiv.className = 'doc-req-card';
        const docName = typeof doc === 'object' ? (doc.name || 'Required Document') : doc;

        let html = `
            <div class="doc-req-header">
                <div class="doc-req-icon"><i class="fas fa-file-alt"></i></div>
                <span class="doc-req-name">${docName}</span>
            </div>
            <div class="doc-req-body">
        `;
        
        if (typeof doc === 'object' && doc.required_elements) {
            html += `
                <div>
                <div class="req-elements-label">Required Elements</div>
                <ul class="required-elements">
                    ${doc.required_elements.map(element => `<li>${element}</li>`).join('')}
                </ul>
                </div>
            `;
        }
        
        if (typeof doc === 'object' && doc.visual_reference) {
            html += `
                <div class="visual-reference">
                    <span class="visual-ref-label">Visual Reference</span>
                    <p class="visual-ref-desc">${doc.visual_reference.layout_description || ''}</p>
                    ${doc.visual_reference.key_visual_features ? 
                        `<p class="visual-ref-features">Key features: ${doc.visual_reference.key_visual_features.join(', ')}</p>` : ''
                    }
                    <button class="btn-ref" data-doc-name="${docName}" onclick="handle_doc_reference(this, this.dataset.docName)">
                        <i class="fas fa-eye"></i> See Reference
                    </button>
                </div>
            `;
        }

        html += '</div>';

        docDiv.innerHTML = html;
        container.appendChild(docDiv);
    });
}

function renderRequiredDocsPlaceholder(message) {
    const container = document.getElementById('required-docs-container');
    if (!container) return;
    container.innerHTML = `<p class="req-empty">${message}</p>`;
}

function handleGenerateDocs() {
    const select = document.getElementById('docQuerySelect');
    if (!select) {
        console.error('docQuerySelect element not found');
        showNotification('Dropdown element not found', 'error');
        return;
    }
    
    const id = select.value;
    
    console.log('Selected query ID:', id);
    console.log('Available queries:', savedQueries);
    
    if (!id || id === '') { 
        showNotification('Please select a query from the dropdown', 'warning'); 
        return; 
    }
    
    const query = savedQueries.find(q => q.id === id);
    if (!query) {
        console.error('Query not found for ID:', id);
        showNotification('Selected query not found', 'error');
        return;
    }
    
    console.log('Found query:', query);
    generate_req_docs_ai(id);
}

async function generate_req_docs_ai(queryId) {
    try {
        showNotification('Generating documents...', 'info');
        
        // Disable button during generation
        const generateBtn = document.getElementById('generateDocsBtn');
        const originalText = generateBtn.textContent;
        generateBtn.textContent = 'Generating...';
        generateBtn.disabled = true;
        
        const res = await fetch(`/generate_documents/${queryId}`, { method: "POST" });
        const data = await res.json();

        if (data.status === "success") {
            showNotification("Documents generated successfully!", 'success');
            
            // Reload queries to get updated data
            await loadSavedQueries();
            
            // Render the enhanced documents
            renderDocsEnhanced(data.documents);
        } else {
            showNotification(data.message || "Failed to generate documents", "error");
        }
    } catch (err) {
        console.error(err);
        showNotification("Error generating documents", "error");
    } finally {
        // Re-enable button
        const generateBtn = document.getElementById('generateDocsBtn');
        if (generateBtn) {
            generateBtn.textContent = 'Get required Documents';
            generateBtn.disabled = false;
        }
    }
}

async function updateUserComplianceDisplay() {
    try {
        const userId = currentUserId || "{{ user.id }}";
        const response = await fetch(`/user/${userId}/document_status`);
        const data = await response.json();
        
        if (data.status === 'success' && data.compliance_summary) {
            const scoreEl = document.getElementById('userComplianceScore');
            if (scoreEl) {
                const score = data.compliance_summary.average_authenticity_score;
                scoreEl.textContent = `${score}%`;
                
                // Update score styling
                scoreEl.className = 'compliance-score';
                if (score >= 80) {
                    scoreEl.classList.add('score-high');
                } else if (score >= 60) {
                    scoreEl.classList.add('score-medium');
                } else {
                    scoreEl.classList.add('score-low');
                }
            }
        }
    } catch (err) {
        console.error('Error updating compliance display:', err);
    }
}

// async function viewDocumentDetails(docId) {
//     try {
//         const response = await fetch(`/document/details/${docId}`);
//         const data = await response.json();
        
//         if (data.error) {
//             showNotification(data.error, 'error');
//             return;
//         }
        
//         // Show detailed modal with document information
//         showDocumentModal(data);
//     } catch (err) {
//         console.error('Error fetching document details:', err);
//         showNotification('Error loading document details', 'error');
//     }
// }

function showDocumentModal(docData) {
    const modal = document.getElementById('documentModal');
    const content = document.getElementById('modalContent');
    
    if (!modal || !content) return;
    
    let html = `
        <h3>${docData.name}</h3>
        <p><strong>Uploaded:</strong> ${new Date(docData.uploaded_at).toLocaleDateString()}</p>
    `;
    
    if (docData.scan_result) {
        const result = docData.scan_result;
        html += `
            <div class="scan-details">
                <h4>Scan Results</h4>
                <p><strong>Overall Validity:</strong> ${result.overall_validity || 'Unknown'}</p>
                ${result.authenticity_score ? `<p><strong>Authenticity Score:</strong> ${result.authenticity_score}%</p>` : ''}
                
                ${result.required_elements_check ? `
                    <h5>Required Elements Check:</h5>
                    <p>All Present: ${result.required_elements_check.all_present ? 'Yes' : 'No'}</p>
                    ${result.required_elements_check.missing_elements && result.required_elements_check.missing_elements.length > 0 ? 
                        `<p>Missing: ${result.required_elements_check.missing_elements.join(', ')}</p>` : ''
                    }
                    ${result.required_elements_check.present_elements && result.required_elements_check.present_elements.length > 0 ? 
                        `<p>Present: ${result.required_elements_check.present_elements.join(', ')}</p>` : ''
                    }
                ` : ''}
                
                ${result.detailed_analysis ? `
                    <h5>Detailed Analysis:</h5>
                    <p>${result.detailed_analysis}</p>
                ` : ''}
                
                ${result.recommendations && result.recommendations.length > 0 ? `
                    <h5>Recommendations:</h5>
                    <ul>
                        ${result.recommendations.map(rec => `<li>${rec}</li>`).join('')}
                    </ul>
                ` : ''}
            </div>
        `;
    }
    
    content.innerHTML = html;
    modal.style.display = 'block';
}

function closeDocumentModal() {
    const modal = document.getElementById('documentModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Load initial data
    loadSavedQueries();
    updateUserComplianceDisplay();
    
    // Query selection change handler
    const docSel = document.getElementById('docQuerySelect');
    if (docSel) {
        docSel.addEventListener('change', e => {
            const queryId = e.target.value;
            if (!queryId) {
                renderRequiredDocsPlaceholder('Select a query to view or generate required documents.');
                return;
            }

            const query = savedQueries.find(q => q.id === queryId);
            if (query && query.documents && query.documents.length) {
                renderDocsEnhanced(query.documents);
            } else {
                renderRequiredDocsPlaceholder('No required documents generated for this query yet. Click "Get Required Documents".');
            }
        });
    }
    
    // Modal close on outside click
    window.addEventListener('click', (event) => {
        const modal = document.getElementById('documentModal');
        if (event.target === modal) {
            closeDocumentModal();
        }
    });
});

async function handle_doc_reference(button, requestedDocName) {
    if (referenceRequestInFlight) {
        showNotification("Reference generation is already in progress", "info");
        return;
    }

    const refButtons = document.querySelectorAll('.btn-ref, .add-btn');
    const originalButtonHtml = button ? button.innerHTML : '';

    try {
        referenceRequestInFlight = true;
        refButtons.forEach(btn => {
            btn.disabled = true;
            btn.style.pointerEvents = 'none';
            btn.style.opacity = '0.6';
        });
        if (button) {
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
        }

        // Example: grab currently selected query & document
        const select = document.getElementById("docQuerySelect");
        if (!select || !select.value) {
            showNotification("Please select a query first", "warning");
            return;
        }

        const queryId = select.value;
        const query = savedQueries.find(q => q.id === queryId);

        if (!query || !query.documents || query.documents.length === 0) {
            showNotification("No documents found for this query", "warning");
            return;
        }

        // Pick the first document (or let user choose later)
        const docName = requestedDocName || query.documents[0].name || query.documents[0];

        // Call backend to generate HTML reference
        const res = await fetch("/generate_doc_reference", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                doc_name: docName,
                query_data: query   // pass full query object
            })
        });

        const data = await res.json();

        if (data.success) {
            showNotification("Reference generated successfully!", "success");
            // Redirect to see the generated HTML
            window.location.href = "/see_reference";
        } else {
            showNotification(data.message || "Failed to generate reference", "error");
        }
    } catch (err) {
        console.error("Error generating reference:", err);
        showNotification("Error generating reference", "error");
    } finally {
        referenceRequestInFlight = false;
        refButtons.forEach(btn => {
            btn.disabled = false;
            btn.style.pointerEvents = '';
            btn.style.opacity = '';
        });
        if (button && originalButtonHtml) {
            button.innerHTML = originalButtonHtml;
        }
    }
}
