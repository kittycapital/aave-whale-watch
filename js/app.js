/**
 * 🐋 AAVE 고래 트래커 - Dashboard App
 * 대형 포지션 & 청산 리스크 모니터링
 */

// ===== Configuration =====
const CONFIG = {
    chains: ['ethereum', 'arbitrum', 'polygon', 'base'],
    chainNames: {
        ethereum: 'Ethereum',
        arbitrum: 'Arbitrum',
        polygon: 'Polygon',
        base: 'Base'
    },
    chainIcons: {
        ethereum: '◆',
        arbitrum: '🔵',
        polygon: '🟣',
        base: '🔷'
    },
    chainColors: {
        ethereum: '#627eea',
        arbitrum: '#28a0f0',
        polygon: '#8247e5',
        base: '#0052ff'
    },
    hfThresholds: {
        danger: 1.1,
        warning: 1.3,
        safe: 1.5
    },
    minWhaleValue: 200000
};

// ===== State =====
let state = {
    data: {},
    currentChain: 'all',
    assetType: 'collateral',
    sortBy: 'hf-asc'
};

// ===== Data Loading =====
async function loadData() {
    try {
        const promises = CONFIG.chains.map(chain => 
            fetch(`data/${chain}.json`)
                .then(res => res.ok ? res.json() : { positions: [], meta: {} })
                .catch(() => ({ positions: [], meta: {} }))
        );
        
        const results = await Promise.all(promises);
        
        CONFIG.chains.forEach((chain, index) => {
            state.data[chain] = results[index];
        });
        
        updateDashboard();
    } catch (error) {
        console.error('데이터 로딩 실패:', error);
        showError();
    }
}

// ===== Helper Functions =====
function formatNumber(num, decimals = 2) {
    if (num === undefined || num === null || isNaN(num)) return '-';
    if (num >= 1e9) return (num / 1e9).toFixed(decimals) + 'B';
    if (num >= 1e6) return (num / 1e6).toFixed(decimals) + 'M';
    if (num >= 1e3) return (num / 1e3).toFixed(decimals) + 'K';
    return num.toFixed(decimals);
}

function formatUSD(num) {
    if (num === undefined || num === null || isNaN(num)) return '-';
    return '$' + formatNumber(num);
}

function formatPrice(num) {
    if (num === undefined || num === null || isNaN(num)) return '-';
    if (num >= 1000) return '$' + num.toLocaleString('en-US', { maximumFractionDigits: 0 });
    if (num >= 1) return '$' + num.toFixed(2);
    return '$' + num.toFixed(4);
}

function shortenAddress(address) {
    if (!address) return '-';
    return address.slice(0, 6) + '...' + address.slice(-4);
}

function getHFClass(hf) {
    if (hf < CONFIG.hfThresholds.danger) return 'danger';
    if (hf < CONFIG.hfThresholds.warning) return 'warning';
    return 'safe';
}

function getHFStatus(hf) {
    if (hf < CONFIG.hfThresholds.danger) return '위험';
    if (hf < CONFIG.hfThresholds.warning) return '주의';
    return '관찰';
}

/**
 * 청산가격 계산
 * 청산가격 = 대출금액 / (담보수량 × 청산임계값)
 * Mixed 포지션은 계산 불가
 */
function calculateLiquidationPrice(position) {
    const { borrowValue, collateralAmount, liquidationThreshold, collateralAsset } = position;
    
    // Mixed 포지션은 청산가격 계산 불가
    if (collateralAsset === 'Mixed' || !collateralAsset) {
        return null;
    }
    
    // 담보수량이 1이면 실제 데이터가 아님 (placeholder)
    if (!collateralAmount || collateralAmount <= 1 || !liquidationThreshold) {
        return null;
    }
    
    const liqPrice = borrowValue / (collateralAmount * liquidationThreshold);
    return liqPrice;
}

function getAllPositions() {
    let positions = [];
    
    if (state.currentChain === 'all') {
        CONFIG.chains.forEach(chain => {
            const chainData = state.data[chain];
            if (chainData?.positions) {
                positions = positions.concat(
                    chainData.positions.map(p => ({ ...p, chain }))
                );
            }
        });
    } else {
        const chainData = state.data[state.currentChain];
        if (chainData?.positions) {
            positions = chainData.positions.map(p => ({ ...p, chain: state.currentChain }));
        }
    }
    
    return positions;
}

// ===== Dashboard Update =====
function updateDashboard() {
    updateLastUpdateTime();
    updateChainCounts();
    updateStats();
    updateHeatmap();
    updateWhaleList();
    updateAssetChart();
    updateChainChart();
    updatePositionTable();
}

function updateLastUpdateTime() {
    const now = new Date();
    const timeStr = now.toLocaleString('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Asia/Seoul'
    });
    document.getElementById('lastUpdate').textContent = timeStr + ' KST';
}

function updateChainCounts() {
    let totalCount = 0;
    
    CONFIG.chains.forEach(chain => {
        const count = state.data[chain]?.positions?.length || 0;
        document.getElementById(`count-${chain}`).textContent = count;
        totalCount += count;
    });
    
    document.getElementById('count-all').textContent = totalCount;
}

function updateStats() {
    const positions = getAllPositions();
    
    const criticalCount = positions.filter(p => p.healthFactor < CONFIG.hfThresholds.danger).length;
    const warningCount = positions.filter(p => 
        p.healthFactor >= CONFIG.hfThresholds.danger && 
        p.healthFactor < CONFIG.hfThresholds.warning
    ).length;
    const whaleCount = positions.filter(p => p.collateralValue >= CONFIG.minWhaleValue).length;
    const totalValue = positions.reduce((sum, p) => sum + (p.collateralValue || 0), 0);
    
    document.getElementById('criticalCount').textContent = criticalCount;
    document.getElementById('warningCount').textContent = warningCount;
    document.getElementById('whaleCount').textContent = whaleCount;
    document.getElementById('totalValue').textContent = formatUSD(totalValue);
}

function updateHeatmap() {
    const positions = getAllPositions();
    const grid = document.getElementById('heatmapGrid');
    
    const groups = {};
    
    positions.forEach(p => {
        const asset = p.collateralAsset || 'Unknown';
        const hfClass = getHFClass(p.healthFactor);
        const key = `${asset}-${hfClass}`;
        
        if (!groups[key]) {
            groups[key] = {
                asset,
                hfClass,
                count: 0,
                totalValue: 0
            };
        }
        groups[key].count++;
        groups[key].totalValue += p.collateralValue || 0;
    });
    
    const sortedGroups = Object.values(groups)
        .sort((a, b) => {
            const classOrder = { danger: 0, warning: 1, safe: 2 };
            if (classOrder[a.hfClass] !== classOrder[b.hfClass]) {
                return classOrder[a.hfClass] - classOrder[b.hfClass];
            }
            return b.totalValue - a.totalValue;
        });
    
    if (sortedGroups.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <p>데이터가 없습니다</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = sortedGroups.map(g => {
        const hfRange = g.hfClass === 'danger' ? '1.0~1.1' : 
                        g.hfClass === 'warning' ? '1.1~1.3' : '1.3~1.5';
        return `
            <div class="heatmap-cell ${g.hfClass}">
                <span class="asset">${g.asset}</span>
                <span class="count">${g.count}</span>
                <span class="hf-range">HF ${hfRange}</span>
            </div>
        `;
    }).join('');
}

function updateWhaleList() {
    const positions = getAllPositions()
        .filter(p => p.collateralValue >= CONFIG.minWhaleValue)
        .sort((a, b) => b.collateralValue - a.collateralValue)
        .slice(0, 10);
    
    const list = document.getElementById('whaleList');
    
    if (positions.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🐋</div>
                <p>$200K 이상 포지션 없음</p>
            </div>
        `;
        return;
    }
    
    list.innerHTML = positions.map((p, i) => {
        const hfClass = getHFClass(p.healthFactor);
        const liqPrice = calculateLiquidationPrice(p);
        const liqPriceStr = liqPrice ? `청산가: ${formatPrice(liqPrice)}` : '';
        
        return `
            <div class="whale-item">
                <div class="whale-rank ${i < 3 ? 'top-3' : ''}">${i + 1}</div>
                <div class="whale-info">
                    <span class="whale-address">${shortenAddress(p.address)}</span>
                    <span class="whale-assets">${p.collateralAsset} → ${p.borrowAsset}</span>
                    ${liqPriceStr ? `<span class="whale-liq-price">⚠️ ${liqPriceStr}</span>` : ''}
                </div>
                <div class="whale-value">
                    <span class="whale-amount">${formatUSD(p.collateralValue)}</span>
                    <span class="whale-hf ${hfClass}">HF ${p.healthFactor?.toFixed(2)}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ===== Charts =====
let assetChart = null;
let chainChart = null;

function updateAssetChart() {
    const positions = getAllPositions();
    const ctx = document.getElementById('assetChart').getContext('2d');
    
    const assetKey = state.assetType === 'collateral' ? 'collateralAsset' : 'borrowAsset';
    const valueKey = state.assetType === 'collateral' ? 'collateralValue' : 'borrowValue';
    
    const assetTotals = {};
    positions.forEach(p => {
        const asset = p[assetKey] || 'Unknown';
        assetTotals[asset] = (assetTotals[asset] || 0) + (p[valueKey] || 0);
    });
    
    const sortedAssets = Object.entries(assetTotals)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);
    
    const labels = sortedAssets.map(([asset]) => asset);
    const data = sortedAssets.map(([, value]) => value);
    
    const colors = [
        '#00f0ff', '#a855f7', '#ec4899', '#22c55e',
        '#eab308', '#f97316', '#ef4444', '#64748b'
    ];
    
    if (assetChart) {
        assetChart.destroy();
    }
    
    assetChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: colors,
                borderWidth: 0,
                hoverOffset: 10
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#a0a0a0',
                        font: { family: "'Noto Sans KR', sans-serif", size: 11 },
                        padding: 10,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: '#1a1a1a',
                    titleColor: '#fff',
                    bodyColor: '#a0a0a0',
                    borderColor: '#222',
                    borderWidth: 1,
                    callbacks: {
                        label: (context) => {
                            return ` ${context.label}: ${formatUSD(context.raw)}`;
                        }
                    }
                }
            }
        }
    });
    
    updateUtilizationList(sortedAssets);
}

function updateUtilizationList(sortedAssets) {
    const list = document.getElementById('utilizationList');
    const maxValue = sortedAssets[0]?.[1] || 1;
    
    list.innerHTML = sortedAssets.slice(0, 5).map(([asset, value]) => {
        const percent = (value / maxValue * 100).toFixed(0);
        const color = `hsl(${180 - percent * 1.2}, 80%, 50%)`;
        return `
            <div class="utilization-item">
                <span class="utilization-asset">${asset}</span>
                <div class="utilization-bar">
                    <div class="utilization-fill" style="width: ${percent}%; background: ${color}"></div>
                </div>
                <span class="utilization-value">${formatUSD(value)}</span>
            </div>
        `;
    }).join('');
}

function updateChainChart() {
    const ctx = document.getElementById('chainChart').getContext('2d');
    
    const chainData = CONFIG.chains.map(chain => {
        const positions = state.data[chain]?.positions || [];
        return {
            chain,
            collateral: positions.reduce((sum, p) => sum + (p.collateralValue || 0), 0),
            borrow: positions.reduce((sum, p) => sum + (p.borrowValue || 0), 0),
            count: positions.length
        };
    });
    
    if (chainChart) {
        chainChart.destroy();
    }
    
    chainChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: chainData.map(d => CONFIG.chainNames[d.chain]),
            datasets: [
                {
                    label: '담보',
                    data: chainData.map(d => d.collateral),
                    backgroundColor: CONFIG.chains.map(c => CONFIG.chainColors[c] + '99'),
                    borderColor: CONFIG.chains.map(c => CONFIG.chainColors[c]),
                    borderWidth: 1
                },
                {
                    label: '대출',
                    data: chainData.map(d => d.borrow),
                    backgroundColor: CONFIG.chains.map(c => CONFIG.chainColors[c] + '44'),
                    borderColor: CONFIG.chains.map(c => CONFIG.chainColors[c]),
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    grid: { color: '#222' },
                    ticks: { color: '#a0a0a0' }
                },
                y: {
                    grid: { color: '#222' },
                    ticks: {
                        color: '#a0a0a0',
                        callback: (value) => formatUSD(value)
                    }
                }
            },
            plugins: {
                legend: {
                    labels: { color: '#a0a0a0' }
                },
                tooltip: {
                    backgroundColor: '#1a1a1a',
                    titleColor: '#fff',
                    bodyColor: '#a0a0a0',
                    callbacks: {
                        label: (context) => ` ${context.dataset.label}: ${formatUSD(context.raw)}`
                    }
                }
            }
        }
    });
    
    updateChainCards(chainData);
}

function updateChainCards(chainData) {
    const container = document.getElementById('chainCards');
    
    container.innerHTML = chainData.map(d => `
        <div class="chain-card ${d.chain}">
            <div class="chain-card-name">${CONFIG.chainIcons[d.chain]} ${CONFIG.chainNames[d.chain]}</div>
            <div class="chain-card-stats">
                <div class="chain-card-stat">
                    <span>포지션</span>
                    <span>${d.count}개</span>
                </div>
                <div class="chain-card-stat">
                    <span>담보</span>
                    <span>${formatUSD(d.collateral)}</span>
                </div>
                <div class="chain-card-stat">
                    <span>대출</span>
                    <span>${formatUSD(d.borrow)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function updatePositionTable() {
    const positions = getAllPositions();
    
    const sorted = [...positions].sort((a, b) => {
        switch (state.sortBy) {
            case 'hf-asc': return a.healthFactor - b.healthFactor;
            case 'hf-desc': return b.healthFactor - a.healthFactor;
            case 'value-desc': return b.collateralValue - a.collateralValue;
            case 'value-asc': return a.collateralValue - b.collateralValue;
            default: return 0;
        }
    });
    
    const table = document.getElementById('positionTable');
    
    if (sorted.length === 0) {
        table.innerHTML = `
            <tr>
                <td colspan="9" class="empty-state">
                    <div class="empty-state-icon">📋</div>
                    <p>표시할 포지션이 없습니다</p>
                </td>
            </tr>
        `;
        return;
    }
    
    table.innerHTML = sorted.slice(0, 50).map(p => {
        const hfClass = getHFClass(p.healthFactor);
        const liqPrice = calculateLiquidationPrice(p);
        const liqPriceStr = liqPrice ? `${p.collateralAsset} ${formatPrice(liqPrice)}` : '-';
        
        return `
            <tr>
                <td><span class="chain-badge ${p.chain}">${CONFIG.chainIcons[p.chain]} ${CONFIG.chainNames[p.chain]}</span></td>
                <td class="address-cell">${shortenAddress(p.address)}</td>
                <td class="hf-cell ${hfClass}">${p.healthFactor?.toFixed(3)}</td>
                <td>${p.collateralAsset || '-'}</td>
                <td class="amount-cell">${formatUSD(p.collateralValue)}</td>
                <td>${p.borrowAsset || '-'}</td>
                <td class="amount-cell">${formatUSD(p.borrowValue)}</td>
                <td class="liq-price-cell">${liqPriceStr}</td>
                <td><span class="status-cell ${hfClass}">${getHFStatus(p.healthFactor)}</span></td>
            </tr>
        `;
    }).join('');
}

// ===== Event Handlers =====
function initEventListeners() {
    document.querySelectorAll('.chain-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.chain-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            state.currentChain = tab.dataset.chain;
            updateDashboard();
        });
    });
    
    document.querySelectorAll('.card-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.card-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            state.assetType = tab.dataset.type;
            updateAssetChart();
        });
    });
    
    document.getElementById('sortSelect').addEventListener('change', (e) => {
        state.sortBy = e.target.value;
        updatePositionTable();
    });
}

function showError() {
    document.querySelectorAll('.card-body').forEach(body => {
        body.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">⚠️</div>
                <p>데이터를 불러올 수 없습니다</p>
            </div>
        `;
    });
}

// ===== Initialize =====
document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    loadData();
});
