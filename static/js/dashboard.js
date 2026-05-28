// Toggle sidebar on mobile
document.getElementById('menuToggle')?.addEventListener('click', function() {
    document.querySelector('.sidebar').classList.toggle('active');
});

// Progress Circle Init
document.addEventListener('DOMContentLoaded', function() {
    const progressElements = document.querySelectorAll('.circle-progress');
    progressElements.forEach(el => {
        const progress = el.getAttribute('data-progress');
        el.style.background = `conic-gradient(var(--accent) calc(${progress} * 3.6deg), var(--gray-light) 0deg)`;
    });
});

function refreshProgress() {
    showNotification("Progress refresh is not yet connected to backend", "info");
}

// DEADLINES

// Add Deadline
function addDeadline() {
    const title = prompt("Enter deadline title:");
    if (title) {
        const date = prompt("Enter deadline date (YYYY-MM-DD):");
        if (date) {
            fetch("/deadline/add", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({title, date})
            })
            .then(res => res.json())
            .then(data => {
                showNotification("Deadline added successfully!");
                setTimeout(() => location.reload(), 1000);
            })
            .catch(err => showNotification("Error adding deadline", "error"));
        }
    }
}

// Toggle Deadline
function toggleDeadline(id, completed) {
    fetch(`/deadline/update/${id}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({completed})
    })
    .then(res => res.json())
    .then(() => showNotification(`Deadline marked as ${completed ? 'completed' : 'pending'}`))
    .catch(() => showNotification("Error updating deadline", "error"));
}

// Edit Deadline
function editDeadline(id) {
    const newTitle = prompt("Edit deadline title:");
    if (newTitle) {
        fetch(`/deadline/edit/${id}`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({title: newTitle})
        })
        .then(res => res.json())
        .then(() => {
            showNotification("Deadline updated successfully!");
            setTimeout(() => location.reload(), 1000);
        })
        .catch(() => showNotification("Error updating deadline", "error"));
    }
}

// Delete Deadline
function deleteDeadline(id) {
    if (confirm("Are you sure you want to delete this deadline?")) {
        fetch(`/deadline/delete/${id}`, {method: "DELETE"})
            .then(() => {
                showNotification("Deadline deleted successfully!");
                setTimeout(() => location.reload(), 1000);
            })
            .catch(() => showNotification("Error deleting deadline", "error"));
    }
}

// QUERY 

// NEW QUERY TOGGLE
document.addEventListener("DOMContentLoaded", () => {
    const newQueryBtn = document.getElementById("newQueryBtn");
    const queryInputContainer = document.getElementById("queryInputContainer");
    const closeQueryBtn = document.getElementById("closeQueryBtn");
    const userQuery = document.getElementById("userQuery");

    if (newQueryBtn && queryInputContainer) {
        newQueryBtn.addEventListener("click", () => {
            queryInputContainer.style.display = "block";
            userQuery.focus();
        });
    }

    if (closeQueryBtn && queryInputContainer) {
        closeQueryBtn.addEventListener("click", () => {
            queryInputContainer.style.display = "none";
            userQuery.value = ""; // clear input on close
        });
    }
});

// Update saveQuery to hide after saving
function saveQuery() {
    const queryText = document.getElementById("userQuery").value;
    if (!queryText.trim()) {
        showNotification("Please enter a query to save", "warning");
        return;
    }

    fetch("/save_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({query: queryText})
    })
    .then(res => res.json())
    .then(() => {
        showNotification("Query saved successfully!");
        document.getElementById("queryInputContainer").style.display = "none";
        document.getElementById("userQuery").value = "";
        setTimeout(() => location.reload(), 1000);
    })
    .catch(() => showNotification("Error saving query", "error"));
}


// Analyze Query
function analyseQuery() {
    fetch("/analyse_query", {method: "POST"})
    .then(res => res.json())
    .then(data => {
        alert(data.result || "Analysis complete!");
    })
    .catch(() => showNotification("Error analyzing query", "error"));
}

// NOTIFICATIONS 
function showNotification(message, type = "success") {
    const existingNotification = document.querySelector('.notification');
    if (existingNotification) existingNotification.remove();

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">&times;</button>
    `;

    if (!document.getElementById('notification-styles')) {
        const styles = document.createElement('style');
        styles.id = 'notification-styles';
        styles.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 15px 20px;
                border-radius: 8px;
                color: white;
                display: flex;
                align-items: center;
                justify-content: space-between;
                min-width: 300px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                z-index: 1000;
                animation: slideIn 0.3s ease;
            }
            .notification-success { background: var(--success); }
            .notification-error { background: var(--danger); }
            .notification-warning { background: var(--warning); }
            .notification-info { background: var(--accent); }
            .notification button {
                background: none;
                border: none;
                color: white;
                font-size: 20px;
                cursor: pointer;
                margin-left: 15px;
            }
            @keyframes slideIn {
                from { transform: translateX(100px); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(styles);
    }

    document.body.appendChild(notification);

    setTimeout(() => {
        if (notification.parentElement) notification.remove();
    }, 5000);
}
function scan_query(queryText) {
    if (!queryText || !queryText.trim()) {
        showNotification("Invalid query text", "error");
        return;
    }

    fetch("/analyse_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({query: queryText})
    })
    .then(async res => {
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || `HTTP error ${res.status}`);
        }
        return data;
    })
    .then(data => {
        if (data.result) {
            showNotification("Analysis complete!");
            const content = `
                <p><strong>Status:</strong> ${data.result.status}</p>
                <p><strong>Message:</strong> ${data.result.message}</p>
            `;
            const analysisContent = document.getElementById("analysisContent");
            const analysisResults = document.getElementById("analysisResults");
            const analysisPlaceholder = document.getElementById("analysisPlaceholder");

            if (analysisContent) analysisContent.innerHTML = content;
            if (analysisResults) {
                analysisResults.style.display = "block";
                analysisResults.classList.add("open");
            }
            if (analysisPlaceholder) analysisPlaceholder.style.display = "none";
            // setTimeout(() => location.reload(), 1500);
        } else {
            showNotification(data.error || "Analysis failed", "error");
        }
    })
    .catch(err => showNotification(err.message || "Error analyzing query", "error"));
}

async function generate_deadlines_ai(queryId) {
    console.log("=== FRONTEND DEBUG ===");
    console.log("Query ID:", queryId);
    
    try {
        // Show loading state
        const btn = document.getElementById('generateDeadlinesBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
        }
        
        const res = await fetch(`/generate_deadlines/${queryId}`, { 
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            }
        });
        
        console.log("Response status:", res.status);
        
        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        console.log("Response data:", data);
        
        if (data.status === "success") {
            showNotification("Deadlines generated successfully!");
            console.log("Generated deadlines:", data.deadlines);
            
            const queryIndex = savedQueries.findIndex(q => q.id === queryId);
            if (queryIndex !== -1) {
                savedQueries[queryIndex].deadlines = data.deadlines;
                renderGeneratedDeadlines(queryId); 
            }
            
        } else {
            console.error("API Error:", data);
            showNotification(data.message || "Failed to generate deadlines", "error");
        }
    } catch (err) {
        console.error("Frontend Error:", err);
        showNotification("Error generating deadlines", "error");
    } finally {
        const btn = document.getElementById('generateDeadlinesBtn');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Deadlines';
        }
    }
}

// Function to toggle AI deadline completion status
function toggleAiDeadline(queryId, deadlineId, checked) {
    fetch(`/toggle_ai_deadline/${queryId}/${deadlineId}`, {
        method: "POST",
        headers: { 
            "Content-Type": "application/json" 
        },
        body: JSON.stringify({ 
            completed: checked 
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            showNotification(`AI Deadline marked as ${checked ? "completed" : "pending"}`);
            
            const query = savedQueries.find(q => q.id === queryId);
            if (query && query.deadlines) {
                const deadline = query.deadlines.find(d => d.id === deadlineId);
                if (deadline) {
                    deadline.completed = checked;
                }
            }
        } else {
            showNotification(data.message || "Error updating AI deadline", "error");
            const checkbox = document.querySelector(`input[onchange*="${deadlineId}"]`);
            if (checkbox) checkbox.checked = !checked;
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification("Error updating AI deadline", "error");
        const checkbox = document.querySelector(`input[onchange*="${deadlineId}"]`);
        if (checkbox) checkbox.checked = !checked;
    });
}
function renderGeneratedDeadlines(queryId) {
    const ul = document.getElementById('query-deadlines-list');
    if (!ul) return;
    ul.innerHTML = '';
    
    const q = savedQueries.find(x => x.id === queryId);
    if (!q) {
        ul.innerHTML = '<li>No query selected.</li>';
        return;
    }
    
    const dls = Array.isArray(q.deadlines) ? q.deadlines : [];
    if (!dls.length) {
        ul.innerHTML = '<li>No AI-generated deadlines yet. Click "Generate Deadlines".</li>';
        return;
    }
    
    dls.forEach(d => {
        if (d.task && d.due_date) {
            const li = document.createElement('li');
            li.innerHTML = `
                <div class="deadline-content">
                    <label class="checkbox-container">
                        <input type="checkbox" 
                               ${d.completed ? 'checked' : ''} 
                               onchange="toggleAiDeadline('${queryId}', '${d.id}', this.checked)">
                        <span class="checkmark"></span>
                    </label>
                    <div class="deadline-info">
                        <span class="deadline-title">${d.task}</span>
                        <span class="deadline-date">Due: ${d.due_date}</span>
                    </div>
                </div>
            `;
            ul.appendChild(li);
        }
    });
}

//  FIND USERS 
function find_users(queryId, button) {
    if (!queryId) {
        showNotification("Invalid query ID", "error");
        return;
    }

    if (button) {
        button.disabled = true;
        button.style.pointerEvents = "none";
        button.style.opacity = "0.65";
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Finding...';
    }

    window.location.href = `/find_users/${queryId}`;
}
