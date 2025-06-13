import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Box, Button, TextField, Checkbox, FormControlLabel,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, Typography, Select, MenuItem
} from '@mui/material';
import { createTheme, ThemeProvider, styled } from '@mui/material/styles';

// Theme setup with button styles
const theme = createTheme({
  palette: {
    mode: 'light',
  },
});

const BlueButton = styled(Button)(({ theme }) => ({
  backgroundColor: theme.palette.primary.main,
  color: theme.palette.common.white,
  '&:hover': {
    backgroundColor: theme.palette.primary.dark,
  },
}));

const RedButton = styled(Button)(({ theme }) => ({
  backgroundColor: '#f44336',
  color: theme.palette.common.white,
  '&:hover': {
    backgroundColor: '#d32f2f',
  },
}));

const GreenButton = styled(Button)(({ theme }) => ({
  backgroundColor: '#36f446',
  color: theme.palette.common.white,
  '&:hover': {
    backgroundColor: '#2fd33a',
  },
}));

function TankManager() {
  const [tanks, setTanks] = useState([]);
  const [form, setForm] = useState({ name: '', blend: '', is_empty: true, current_volume: '', capacity: '' });
  const [editing, setEditing] = useState(null);
  const [file, setFile] = useState(null);
  const [blendSummary, setBlendSummary] = useState(null);
  const [transferPlan, setTransferPlan] = useState([]);
  const [blendName, setBlendName] = useState('');
  const [historyList, setHistoryList] = useState([]);
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [historyDetails, setHistoryDetails] = useState(null);

  useEffect(() => {
    fetchTanks();
    fetchBlendHistoryList();
  }, []);

  const fetchTanks = async () => {
    const res = await axios.get('/tanks');
    setTanks(res.data);
  };

  const fetchBlendSummary = async () => {
    const res = await axios.get('/blend/validate');
    setBlendSummary(res.data);
  };

  const fetchTransferPlan = async () => {
  try {
    const res = await axios.get('/blend/plan');
    setTransferPlan(res.data.transfer_plan);
    setBlendSummary({ blend_percentages: res.data.blend_percentages });
  } catch (error) {
    console.error('Transfer plan generation failed:', error.response?.data || error.message);
    alert(error.response?.data?.message || 'Failed to generate transfer plan');
  }
  };

  const fetchBlendHistoryList = async () => {
    const res = await axios.get('/blend/history');
    setHistoryList(res.data);
  };

  const fetchBlendHistoryDetails = async (name) => {
    const res = await axios.get(`/blend/history/${name}`);
    setHistoryDetails(res.data);
  };

  const saveCurrentBlend = async () => {
    if (!blendName || transferPlan.length === 0 || !blendSummary) return;
    await axios.post('/blend/save', {
      blend_name: blendName,
      transfer_plan: transferPlan,
      blend_percentages: blendSummary.blend_percentages,
    });
    setBlendName('');
    fetchBlendHistoryList();
  };

  const handleSubmit = async () => {
    const data = { ...form, is_empty: Boolean(form.is_empty) };
    if (editing !== null) {
      await axios.put(`/tanks/${editing}`, data);
    } else {
      await axios.post('/tanks', data);
    }
    fetchTanks();
    setForm({ name: '', blend: '', is_empty: true, current_volume: '', capacity: '' });
    setEditing(null);
  };

  const handleEdit = (tank) => {
    setForm(tank);
    setEditing(tank.name);
  };

  const handleDelete = async (name) => {
    await axios.delete(`/tanks/${name}`);
    fetchTanks();
  };

  // File input change
  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  // Upload button action
  const handleCSVUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      await axios.post('/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      fetchTanks(); // Reload tanks after upload
    } catch (error) {
      console.error('Upload failed:', error);
    }
  };

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ p: 4 }}>
        <Typography variant="h4" gutterBottom>Bryce's Blender, an efficient wine blending app</Typography>

        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField label="Tank Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <TextField label="Blend Number" value={form.blend} onChange={(e) => setForm({ ...form, blend: e.target.value })} />
          <FormControlLabel
            control={<Checkbox checked={form.is_empty} onChange={(e) => setForm({ ...form, is_empty: e.target.checked })} />}
            label="Is Empty"
          />
          <TextField label="Current Volume" value={form.current_volume} onChange={(e) => setForm({ ...form, current_volume: e.target.value })} />
          <TextField label="Capacity" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} />
          <BlueButton onClick={handleSubmit}>{editing ? 'Update' : 'Add'}</BlueButton>
        </Box>

        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Tank</TableCell>
                <TableCell>Blend</TableCell>
                <TableCell>Empty?</TableCell>
                <TableCell>Current Volume</TableCell>
                <TableCell>Capacity</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tanks.map((tank) => (
                <TableRow key={tank.name}>
                  <TableCell>{tank.name}</TableCell>
                  <TableCell>{tank.blend}</TableCell>
                  <TableCell>{tank.is_empty ? 'Yes' : 'No'}</TableCell>
                  <TableCell>{tank.current_volume}</TableCell>
                  <TableCell>{tank.capacity}</TableCell>
                  <TableCell>
                    <BlueButton onClick={() => handleEdit(tank)} sx={{ mr: 1 }}>Edit</BlueButton>
                    <RedButton onClick={() => handleDelete(tank.name)}>Delete</RedButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        <Box sx={{ mt: 3 }}>
          <Typography variant="h6">Upload CSV</Typography>
          <input type="file" accept=".csv" onChange={handleFileChange} />
          <BlueButton onClick={handleCSVUpload} sx={{ mt: 1 }}>Upload</BlueButton>
        </Box>

        <Box sx={{ mt: 4 }}>
          <Typography variant="h6">Blend Validation & Transfer Plan</Typography>
          <BlueButton onClick={fetchBlendSummary} sx={{ mr: 2, mt: 1 }}>Blend Percentages</BlueButton>
          <BlueButton onClick={fetchTransferPlan} sx={{ mt: 1 }}>Generate Blending Plan</BlueButton>
        </Box>

        {blendSummary && (
          <Box sx={{ mt: 3 }}>
            <Typography>Blend Percentages Total:</Typography>
            <ul>
              {Object.entries(blendSummary.blend_percentages).map(([blend, percent]) => (
                <li key={blend}>{blend}: {percent.toFixed(4)}%</li>
              ))}
            </ul>
          </Box>
        )}

        {transferPlan.length > 0 && (
          <Box sx={{ mt: 4 }}>
            <Typography variant="h6">Transfer Plan</Typography>
            <TextField
              label="Blend Name"
              value={blendName}
              onChange={(e) => setBlendName(e.target.value)}
              sx={{ mr: 2, mb: 2 }}
            />
            <GreenButton onClick={saveCurrentBlend}>Save Blend</GreenButton>
            <TableContainer component={Paper} sx={{ maxWidth: 600, mt: 2 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Volume (gal)</TableCell>
                    <TableCell>Blend</TableCell>
                    <TableCell>From Tank</TableCell>
                    <TableCell>To Tank</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {transferPlan.map((step, index) => (
                    <TableRow key={index}>
                      <TableCell>{Math.round(step.volume)}</TableCell>
                      <TableCell>{step.blend}</TableCell>
                      <TableCell>{step.from}</TableCell>
                      <TableCell>{step.to}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}

        <Box sx={{ mt: 6 }}>
          <Typography variant="h6">View Saved Blend History</Typography>
          <Select
            value={selectedHistory || ''}
            onChange={(e) => {
              setSelectedHistory(e.target.value);
              fetchBlendHistoryDetails(e.target.value);
            }}
            displayEmpty
            sx={{ mb: 2, width: 300 }}
          >
            <MenuItem value="" disabled>Select a saved blend</MenuItem>
            {historyList.map((name) => (
              <MenuItem key={name} value={name}>{name}</MenuItem>
            ))}
          </Select>

          {historyDetails && (
            <Box>
              <Typography>Blend Percentages:</Typography>
              <ul>
                {Object.entries(historyDetails.blend_percentages).map(([blend, percent]) => (
                  <li key={blend}>{blend}: {percent.toFixed(4)}%</li>
                ))}
              </ul>
              <Typography sx={{ mt: 2 }}>Transfer Plan:</Typography>
              <TableContainer component={Paper} sx={{ maxWidth: 600 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Volume (gal)</TableCell>
                      <TableCell>Blend</TableCell>
                      <TableCell>From Tank</TableCell>
                      <TableCell>To Tank</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {historyDetails.transfer_plan.map((step, index) => (
                      <TableRow key={index}>
                        <TableCell>{Math.round(step.volume)}</TableCell>
                        <TableCell>{step.blend}</TableCell>
                        <TableCell>{step.from}</TableCell>
                        <TableCell>{step.to}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </Box>
      </Box>
    </ThemeProvider>
  );
}

export default TankManager;