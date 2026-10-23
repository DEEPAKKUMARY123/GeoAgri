import React, { createContext, useContext, useState, useEffect } from 'react';
import { fetchFullReport, FullReportResponse, PredictRequestPayload } from '../api/client';

import { detectLocationFromCoordinates, DetectedLocationResult, findNearestAgriDistrict } from '../utils/locationDataset';

export type StepNumber = 1 | 2 | 3 | 4;

export interface PresetRegion {
  name: string;
  centroid: [number, number];
  polygon: [number, number][];
  defaultAreaHa: number;
}

export const PRESET_REGIONS: PresetRegion[] = [
  {
    name: "Karnataka Field (Ragi / Coffee / Arecanut / Paddy)",
    centroid: [13.3200, 75.7500],
    polygon: [
      [75.7460, 13.3170],
      [75.7540, 13.3170],
      [75.7540, 13.3230],
      [75.7460, 13.3230],
      [75.7460, 13.3170]
    ],
    defaultAreaHa: 2.85
  },
  {
    name: "California Central Valley, USA (Almonds / Grapes / Citrus)",
    centroid: [36.7500, -120.2500],
    polygon: [
      [-120.2550, 36.7460],
      [-120.2450, 36.7460],
      [-120.2450, 36.7540],
      [-120.2550, 36.7540],
      [-120.2550, 36.7460]
    ],
    defaultAreaHa: 5.40
  },
  {
    name: "Nile Delta, Egypt (Cotton / Wheat / Rice / Maize)",
    centroid: [30.6177, 31.8921],
    polygon: [
      [31.8871, 30.6137],
      [31.8971, 30.6137],
      [31.8971, 30.6217],
      [31.8871, 30.6217],
      [31.8871, 30.6137]
    ],
    defaultAreaHa: 3.20
  },
  {
    name: "Pampas, Argentina (Soybean / Maize / Wheat)",
    centroid: [-34.5000, -61.5000],
    polygon: [
      [-61.5060, -34.5040],
      [-61.4940, -34.5040],
      [-61.4940, -34.4960],
      [-61.5060, -34.4960],
      [-61.5060, -34.5040]
    ],
    defaultAreaHa: 8.50
  },
  {
    name: "Rajasthan Field, India (Pearl Millet / Mustard / Guar)",
    centroid: [26.4500, 73.3000],
    polygon: [
      [73.2957, 26.4461],
      [73.3037, 26.4461],
      [73.3037, 26.4531],
      [73.2957, 26.4531],
      [73.2957, 26.4461]
    ],
    defaultAreaHa: 4.10
  },
  {
    name: "Punjab Field, India (Wheat / Paddy / Mustard)",
    centroid: [30.7512, 75.4987],
    polygon: [
      [75.4964, 30.7502],
      [75.5014, 30.7502],
      [75.5014, 30.7542],
      [75.4964, 30.7542],
      [75.4964, 30.7502]
    ],
    defaultAreaHa: 3.42
  }
];

export interface WorkflowFormData {
  polygonPts: [number, number][];
  pointPt?: [number, number];
  areaHa: number;
  season: "kharif" | "rabi" | "zaid" | "annual" | "perennial";
  irrigationPref: "rainfed" | "supplemental" | "full" | "";
  phInput: string;
  socInput: string;
  selectedPresetName: string;
}

export interface PipelineStage {
  id: number;
  title: string;
  source: string;
  description: string;
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { id: 1, title: "Location Captured", source: "WGS84 Geodesic", description: "Calculating parcel boundaries & centroid" },
  { id: 2, title: "Google Earth Engine", source: "GEE Cloud API", description: "Fetching satellite observations" },
  { id: 3, title: "Sentinel-1 / Sentinel-2", source: "Copernicus Hub", description: "Processing spectral & radar indicators" },
  { id: 4, title: "SoilGrids Profiles", source: "ISRIC Global 250m", description: "Retrieving 3D soil depth properties" },
  { id: 5, title: "NASA POWER Meteorology", source: "NASA Langley", description: "Retrieving climate & rainfall data" },
  { id: 6, title: "Environmental Analysis", source: "Spectral Fusion", description: "Calculating NDVI / NDMI / NDWI" },
  { id: 7, title: "Agronomic Analysis", source: "Model A Engine", description: "Evaluating land suitability" },
  { id: 8, title: "Irrigation Analysis", source: "Model C Engine", description: "Calculating water balance" },
  { id: 9, title: "Climate Risk Scorecard", source: "Model E Engine", description: "Calculating climate risk" },
  { id: 10, title: "Analysis Complete", source: "Decision Engine", description: "Field analysis finalized" },
];

export interface AnalysisStatus {
  locationSelected: boolean;
  predictionComplete: boolean;
  cropAnalysisComplete: boolean;
}

interface WorkflowContextType {
  currentStep: StepNumber;
  maxUnlockedStep: number;
  formData: WorkflowFormData;
  report: FullReportResponse | null;
  loading: boolean;
  isPredicted: boolean;
  analysisStatus: AnalysisStatus;
  detectedLocation: DetectedLocationResult | null;
  theme: 'dark' | 'light';
  pipelineStageIndex: number;
  error: string | null;
  goToStep: (step: StepNumber) => void;
  runPredictNow: () => Promise<boolean>;
  startCropAnalysis: () => void;
  runAnalysis: () => Promise<boolean>;
  updateFormData: (partial: Partial<WorkflowFormData>) => void;
  selectPreset: (preset: PresetRegion) => void;
  isStepAccessible: (step: StepNumber) => boolean;
  toggleTheme: () => void;
  isChatOpen: boolean;
  setIsChatOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

const WorkflowContext = createContext<WorkflowContextType | undefined>(undefined);

const STEP_HASHES: Record<StepNumber, string> = {
  1: '#workspace',
  2: '#field-analysis',
  3: '#crop-prediction',
  4: '#summary'
};

const HASH_TO_STEP: Record<string, StepNumber> = {
  '#workspace': 1,
  '#field-analysis': 2,
  '#crop-prediction': 3,
  '#summary': 4
};

export const WorkflowProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentStep, setCurrentStep] = useState<StepNumber>(1);
  const [maxUnlockedStep, setMaxUnlockedStep] = useState<number>(2); // Steps 1 and 2 are unlocked by default
  const [report, setReport] = useState<FullReportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [isPredicted, setIsPredicted] = useState<boolean>(false);
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus>({
    locationSelected: true,
    predictionComplete: false,
    cropAnalysisComplete: false,
  });
  const [detectedLocation, setDetectedLocation] = useState<DetectedLocationResult | null>(() => {
    return findNearestAgriDistrict(PRESET_REGIONS[0].centroid[0], PRESET_REGIONS[0].centroid[1]);
  });
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('geoagri_theme');
      if (saved === 'light' || saved === 'dark') return saved;
    }
    return 'dark';
  });

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('geoagri_theme', theme);
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  const [pipelineStageIndex, setPipelineStageIndex] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [isChatOpen, setIsChatOpen] = useState<boolean>(false);

  const [formData, setFormData] = useState<WorkflowFormData>({
    polygonPts: PRESET_REGIONS[0].polygon,
    pointPt: undefined,
    areaHa: PRESET_REGIONS[0].defaultAreaHa,
    season: "kharif",
    irrigationPref: "",
    phInput: "",
    socInput: "",
    selectedPresetName: PRESET_REGIONS[0].name
  });

  const updateFormData = (partial: Partial<WorkflowFormData>) => {
    setFormData(prev => ({ ...prev, ...partial }));
    // If coordinates change, require re-predicting
    if (partial.polygonPts || partial.pointPt) {
      setIsPredicted(false);
      setAnalysisStatus(prev => ({
        ...prev,
        predictionComplete: false,
        cropAnalysisComplete: false,
      }));
      setMaxUnlockedStep(2);
    }
  };

  const selectPreset = (preset: PresetRegion) => {
    setFormData(prev => ({
      ...prev,
      polygonPts: preset.polygon,
      pointPt: undefined,
      areaHa: preset.defaultAreaHa,
      selectedPresetName: preset.name
    }));
    setIsPredicted(false);
    setAnalysisStatus(prev => ({
      ...prev,
      predictionComplete: false,
      cropAnalysisComplete: false,
    }));
    setMaxUnlockedStep(2);
  };

  const isStepAccessible = (step: StepNumber): boolean => {
    if (step === 1 || step === 2) return true;
    if (step === 3) return analysisStatus.predictionComplete || isPredicted || report !== null;
    if (step === 4) return analysisStatus.cropAnalysisComplete;
    return false;
  };

  const goToStep = (step: StepNumber) => {
    // Strictly guard Steps 3 and 4:
    // Cannot access Step 3 before Predict Now on Page 2 has finished!
    if (step === 3 && !isStepAccessible(3)) {
      return;
    }
    // Cannot access Step 4 before crop analysis has completed!
    if (step === 4 && !isStepAccessible(4)) {
      return;
    }

    setCurrentStep(step);
    if (step > maxUnlockedStep) {
      setMaxUnlockedStep(step);
    }

    if (typeof window !== 'undefined') {
      window.location.hash = STEP_HASHES[step];
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  // Dynamically detect location from coordinates using Kaggle/ICAR dataset + reverse geocoding
  useEffect(() => {
    const lat = formData.pointPt ? formData.pointPt[1] : (formData.polygonPts[0]?.[1] || 17.3850);
    const lon = formData.pointPt ? formData.pointPt[0] : (formData.polygonPts[0]?.[0] || 78.4867);

    let active = true;
    detectLocationFromCoordinates(lat, lon).then(result => {
      if (active) {
        setDetectedLocation(result);
      }
    });

    return () => {
      active = false;
    };
  }, [formData.pointPt, formData.polygonPts]);

  /**
   * Predict Now triggered from Page 2.
   * Runs the real backend pipeline while advancing live processing stages.
   */
  const runPredictNow = async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    setPipelineStageIndex(1);

    // Live stage progression timer to provide clear feedback during the API fetch
    const stageInterval = setInterval(() => {
      setPipelineStageIndex(prev => (prev < PIPELINE_STAGES.length ? prev + 1 : prev));
    }, 400);

    const payload: PredictRequestPayload = {
      polygon: formData.polygonPts.length > 0 ? formData.polygonPts : undefined,
      point: formData.pointPt,
      season: formData.season,
      limit: 100,
      area_ha: formData.areaHa,
      irrigation_preference: formData.irrigationPref ? (formData.irrigationPref as any) : null,
      manual_soil: (formData.phInput || formData.socInput) ? {
        ph: formData.phInput ? parseFloat(formData.phInput) : null,
        organic_carbon: formData.socInput ? parseFloat(formData.socInput) : null
      } : null
    };

    try {
      const res = await fetchFullReport(payload);
      clearInterval(stageInterval);
      setPipelineStageIndex(PIPELINE_STAGES.length); // All 10 stages complete
      setReport(res);
      setIsPredicted(true);
      setAnalysisStatus(prev => ({
        ...prev,
        predictionComplete: true,
        cropAnalysisComplete: false,
      }));
      setMaxUnlockedStep(3); // Step 3 unlocked; Step 4 remains locked until crop analysis
      return true;
    } catch (err: any) {
      clearInterval(stageInterval);
      setError(err.message || "Failed to connect to GeoAgri AI backend server.");
      return false;
    } finally {
      setLoading(false);
    }
  };

  /**
   * Action when user clicks "Analyse All Crops →" on Page 2.
   * Completes crop analysis readiness and unlocks Step 4.
   */
  const startCropAnalysis = () => {
    setAnalysisStatus(prev => ({
      ...prev,
      cropAnalysisComplete: true,
    }));
    setMaxUnlockedStep(4);
    goToStep(3);
  };

  // Sync hash with browser history
  useEffect(() => {
    const handleHashChange = () => {
      const step = HASH_TO_STEP[window.location.hash];
      if (step) {
        if (step <= 2) {
          setCurrentStep(step);
        } else if (step === 3 && isStepAccessible(3)) {
          setCurrentStep(step);
        } else if (step === 4 && isStepAccessible(4)) {
          setCurrentStep(step);
        }
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [analysisStatus, isPredicted, report, maxUnlockedStep]);

  return (
    <WorkflowContext.Provider
      value={{
        currentStep,
        maxUnlockedStep,
        formData,
        report,
        loading,
        isPredicted,
        analysisStatus,
        detectedLocation,
        theme,
        pipelineStageIndex,
        error,
        goToStep,
        runPredictNow,
        startCropAnalysis,
        runAnalysis: runPredictNow,
        updateFormData,
        selectPreset,
        isStepAccessible,
        toggleTheme,
        isChatOpen,
        setIsChatOpen
      }}
    >
      {children}
    </WorkflowContext.Provider>
  );
};

export const useWorkflow = () => {
  const context = useContext(WorkflowContext);
  if (!context) {
    throw new Error("useWorkflow must be used within a WorkflowProvider");
  }
  return context;
};

