export type ModuleStatus = 'locked' | 'in-progress' | 'completed';

export interface Module {
  id: string;
  number: number;
  title: {
    en: string;
    fr: string;
  };
  level: 1 | 2 | 3 | 4;
  status: ModuleStatus;
  completionPercentage: number;
  estimatedHours: number;
  prerequisites: string[]; // Module IDs
}

export const CURRICULUM_MODULES: Module[] = [
  // Level 1 (Beginner, 60h)
  {
    id: 'M01',
    number: 1,
    title: {
      en: 'Introduction to Public Health',
      fr: 'Introduction à la santé publique'
    },
    level: 1,
    status: 'in-progress',
    completionPercentage: 75,
    estimatedHours: 20,
    prerequisites: []
  },
  {
    id: 'M02', 
    number: 2,
    title: {
      en: 'Health Data Fundamentals',
      fr: 'Fondamentaux des données de santé'
    },
    level: 1,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M01']
  },
  {
    id: 'M03',
    number: 3,
    title: {
      en: 'West African Health Systems',
      fr: 'Systèmes de santé ouest-africains'
    },
    level: 1,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M01']
  },
  // Level 2 (Intermediate, 90h)
  {
    id: 'M04',
    number: 4,
    title: {
      en: 'Epidemiology Principles',
      fr: 'Principes d\'épidémiologie'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M01', 'M02']
  },
  {
    id: 'M05',
    number: 5,
    title: {
      en: 'Disease Surveillance',
      fr: 'Surveillance des maladies'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M04']
  },
  {
    id: 'M06',
    number: 6,
    title: {
      en: 'DHIS2 and Health Information Systems',
      fr: 'DHIS2 et systèmes d\'information sanitaire'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M02', 'M03']
  },
  {
    id: 'M07',
    number: 7,
    title: {
      en: 'Biostatistics Fundamentals',
      fr: 'Fondamentaux de biostatistique'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M02']
  },
  // Level 3 (Advanced, 100h)
  {
    id: 'M08',
    number: 8,
    title: {
      en: 'Advanced Statistics',
      fr: 'Statistiques avancées'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M07']
  },
  {
    id: 'M09',
    number: 9,
    title: {
      en: 'Advanced Epidemiology',
      fr: 'Épidémiologie avancée'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M04', 'M05', 'M07']
  },
  {
    id: 'M10',
    number: 10,
    title: {
      en: 'Health Program Development',
      fr: 'Développement de programmes de santé'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M05', 'M06']
  },
  {
    id: 'M11',
    number: 11,
    title: {
      en: 'Data Visualization',
      fr: 'Visualisation de données'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 15,
    prerequisites: ['M06', 'M07']
  },
  {
    id: 'M12',
    number: 12,
    title: {
      en: 'Health Economics',
      fr: 'Économie de la santé'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 15,
    prerequisites: ['M10']
  },
  // Level 4 (Expert, 70h)
  {
    id: 'M13',
    number: 13,
    title: {
      en: 'Health Policy and Governance',
      fr: 'Politique de santé et gouvernance'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M10', 'M12']
  },
  {
    id: 'M14',
    number: 14,
    title: {
      en: 'Health Systems Strengthening',
      fr: 'Renforcement des systèmes de santé'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 25,
    prerequisites: ['M13']
  },
  {
    id: 'M15',
    number: 15,
    title: {
      en: 'Research Capstone Project',
      fr: 'Projet de recherche final'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M08', 'M09', 'M11', 'M14']
  }
];

export const LEVEL_INFO = {
  1: {
    title: { en: 'Level 1: Beginner', fr: 'Niveau 1 : Débutant' },
    description: { 
      en: 'Foundations, health data intro, West African health systems',
      fr: 'Fondements, introduction aux données de santé, systèmes de santé ouest-africains'
    },
    totalHours: 60,
    modules: ['M01', 'M02', 'M03']
  },
  2: {
    title: { en: 'Level 2: Intermediate', fr: 'Niveau 2 : Intermédiaire' },
    description: { 
      en: 'Epidemiology, surveillance, DHIS2, biostatistics',
      fr: 'Épidémiologie, surveillance, DHIS2, biostatistiques'
    },
    totalHours: 90,
    modules: ['M04', 'M05', 'M06', 'M07']
  },
  3: {
    title: { en: 'Level 3: Advanced', fr: 'Niveau 3 : Avancé' },
    description: { 
      en: 'Advanced stats/epi, health programming, data viz',
      fr: 'Stats/épi avancées, programmation sanitaire, visualisation'
    },
    totalHours: 100,
    modules: ['M08', 'M09', 'M10', 'M11', 'M12']
  },
  4: {
    title: { en: 'Level 4: Expert', fr: 'Niveau 4 : Expert' },
    description: { 
      en: 'Policy, health systems strengthening, research capstone',
      fr: 'Politique, renforcement systèmes de santé, recherche finale'
    },
    totalHours: 70,
    modules: ['M13', 'M14', 'M15']
  }
} as const;

/**
 * Get modules filtered by level
 */
export function getModulesByLevel(level: 1 | 2 | 3 | 4): Module[] {
  return CURRICULUM_MODULES.filter(module => module.level === level);
}

/**
 * Check if a module is unlocked based on prerequisite completion
 */
export function isModuleUnlocked(module: Module, allModules: Module[] = CURRICULUM_MODULES): boolean {
  if (module.prerequisites.length === 0) return true;
  
  const prerequisiteModules = allModules.filter(m => 
    module.prerequisites.includes(m.id)
  );
  
  return prerequisiteModules.every(prereq => prereq.status === 'completed');
}

/**
 * Get progress statistics for a level
 */
export function getLevelProgress(level: 1 | 2 | 3 | 4): {
  completedModules: number;
  totalModules: number;
  averageCompletion: number;
} {
  const levelModules = getModulesByLevel(level);
  const completedModules = levelModules.filter(m => m.status === 'completed').length;
  const totalModules = levelModules.length;
  const averageCompletion = levelModules.reduce((sum, m) => sum + m.completionPercentage, 0) / totalModules;
  
  return {
    completedModules,
    totalModules,
    averageCompletion: Math.round(averageCompletion)
  };
}