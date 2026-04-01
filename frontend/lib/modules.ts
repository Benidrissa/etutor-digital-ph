export type ModuleStatus = 'locked' | 'in-progress' | 'completed';
export type UnitStatus = 'pending' | 'in-progress' | 'completed';

export interface Unit {
  id: string;
  number: number;
  title: {
    en: string;
    fr: string;
  };
  description?: {
    en: string;
    fr: string;
  };
  status: UnitStatus;
  estimatedMinutes: number;
  type: 'lesson' | 'quiz' | 'case-study';
}

export interface Module {
  id: string;
  number: number;
  title: {
    en: string;
    fr: string;
  };
  description?: {
    en: string;
    fr: string;
  };
  level: 1 | 2 | 3 | 4;
  status: ModuleStatus;
  completionPercentage: number;
  estimatedHours: number;
  prerequisites: string[]; // Module IDs
  learningObjectives?: {
    en: string[];
    fr: string[];
  };
  units?: Unit[];
}

export const CURRICULUM_MODULES: Module[] = [
  // Level 1 (Beginner, 60h)
  {
    id: 'M01',
    number: 1,
    title: {
      en: 'Foundations of Public Health',
      fr: 'Fondements de la Santé Publique'
    },
    description: {
      en: 'Concepts, history and global vision of public health in West African context',
      fr: 'Concepts, histoire et vision globale de la santé publique en contexte AOF'
    },
    level: 1,
    status: 'in-progress',
    completionPercentage: 75,
    estimatedHours: 20,
    prerequisites: [],
    learningObjectives: {
      en: [
        'Define public health and distinguish it from clinical medicine',
        'Understand the historical evolution of public health practice',
        'Identify core functions of public health systems in West Africa',
        'Analyze major determinants of health in ECOWAS countries',
        'Apply systems thinking to public health challenges'
      ],
      fr: [
        'Définir la santé publique et la distinguer de la médecine clinique',
        'Comprendre l\'évolution historique de la pratique de santé publique',
        'Identifier les fonctions essentielles des systèmes de santé publique en Afrique de l\'Ouest',
        'Analyser les déterminants majeurs de la santé dans les pays de la CEDEAO',
        'Appliquer la pensée systémique aux défis de santé publique'
      ]
    },
  },
  {
    id: 'M02',
    number: 2,
    title: {
      en: 'Health Data Fundamentals',
      fr: 'Fondamentaux des données de santé'
    },
    description: {
      en: 'Understand, collect and read health data — foundations of statistical reasoning',
      fr: 'Comprendre, collecter et lire les données de santé — les bases du raisonnement statistique'
    },
    level: 1,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 22,
    prerequisites: ['M01']
  },
  {
    id: 'M03',
    number: 3,
    title: {
      en: 'Health Systems in West Africa',
      fr: 'Systèmes de santé en Afrique de l\'Ouest'
    },
    description: {
      en: 'Architecture, financing and performance of health systems in ECOWAS countries',
      fr: 'Architecture, financement et performance des systèmes de santé des pays CEDEAO'
    },
    level: 1,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 18,
    prerequisites: ['M01']
  },
  // Level 2 (Intermediate, 90h)
  {
    id: 'M04',
    number: 4,
    title: {
      en: 'Applied Epidemiology',
      fr: 'Épidémiologie Appliquée'
    },
    description: {
      en: 'Measuring disease in populations — methods and indicators for public health in West Africa',
      fr: 'Mesurer la maladie dans les populations — méthodes et indicateurs pour la santé publique en AOF'
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
      en: 'Biostatistics for Public Health',
      fr: 'Biostatistiques pour la Santé Publique'
    },
    description: {
      en: 'Probabilities, distributions, estimation and hypothesis testing applied to health',
      fr: 'Probabilités, distributions, estimation et tests d\'hypothèse appliqués à la santé'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 28,
    prerequisites: ['M02']
  },
  {
    id: 'M06',
    number: 6,
    title: {
      en: 'Diseases & Health Determinants in West Africa',
      fr: 'Maladies et Déterminants en AOF'
    },
    description: {
      en: 'Epidemiological profile, priority diseases and social determinants of health in West Africa',
      fr: 'Profil épidémiologique, maladies prioritaires et déterminants sociaux de la santé en AOF'
    },
    level: 2,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 22,
    prerequisites: ['M02', 'M03']
  },
  {
    id: 'M07',
    number: 7,
    title: {
      en: 'Public Health Tools & Practice',
      fr: 'Outils et Pratiques de Santé Publique'
    },
    description: {
      en: 'Leadership, community assessment, performance, health data management',
      fr: 'Leadership, évaluation communautaire, performance, gestion des données de santé'
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
      en: 'Digital Epidemiological Surveillance',
      fr: 'Surveillance Épidémiologique Numérique'
    },
    description: {
      en: 'Surveillance systems, early warning and real-time data for response in West Africa',
      fr: 'Systèmes de surveillance, alerte précoce et données en temps réel pour la riposte en AOF'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 22,
    prerequisites: ['M04', 'M05']
  },
  {
    id: 'M09',
    number: 9,
    title: {
      en: 'Advanced Statistics & Data Analysis',
      fr: 'Statistiques Avancées et Analyse de Données'
    },
    description: {
      en: 'Regression, ANOVA, non-parametric tests, survival analysis for health research',
      fr: 'Régression, ANOVA, tests non-paramétriques, analyse de survie — pour la recherche en santé'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 28,
    prerequisites: ['M05']
  },
  {
    id: 'M10',
    number: 10,
    title: {
      en: 'Digital Health & Health Information Systems',
      fr: 'Santé Numérique et HMIS'
    },
    description: {
      en: 'Digital technologies for health in West Africa: DHIS2, mHealth, AI, interoperability',
      fr: 'Technologies numériques pour la santé en AOF : DHIS2, mHealth, IA, interopérabilité'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M06', 'M07']
  },
  {
    id: 'M11',
    number: 11,
    title: {
      en: 'Environmental Health & One Health',
      fr: 'Santé Environnementale et One Health'
    },
    description: {
      en: 'Climate change, water, sanitation, animal-human-environment interface in West Africa',
      fr: 'Changement climatique, eau, assainissement, interface animal-humain-environnement en AOF'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 16,
    prerequisites: ['M04']
  },
  {
    id: 'M12',
    number: 12,
    title: {
      en: 'Maternal, Child & Community Health',
      fr: 'Santé Maternelle, Infantile et Communautaire'
    },
    description: {
      en: 'Reducing maternal and child mortality — MNCH and community health in West Africa',
      fr: 'Réduire la mortalité maternelle et infantile — SMNI et santé communautaire en AOF'
    },
    level: 3,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 20,
    prerequisites: ['M04', 'M06']
  },
  // Level 4 (Expert, 70h)
  {
    id: 'M13',
    number: 13,
    title: {
      en: 'Leadership, Policy & Governance',
      fr: 'Leadership, Politique et Gouvernance'
    },
    description: {
      en: 'Develop and influence public health policies in West Africa',
      fr: 'Élaborer et influencer des politiques de santé publique en Afrique de l\'Ouest'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 22,
    prerequisites: ['M10', 'M12']
  },
  {
    id: 'M14',
    number: 14,
    title: {
      en: 'Advanced Research & Evaluation',
      fr: 'Recherche et Évaluation Avancées'
    },
    description: {
      en: 'Design, conduct and evaluate public health research and health programs',
      fr: 'Concevoir, conduire et évaluer la recherche en santé publique et les programmes de santé'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 24,
    prerequisites: ['M09', 'M13']
  },
  {
    id: 'M15',
    number: 15,
    title: {
      en: 'Integrative Capstone Project',
      fr: 'Projet Intégratif Capstone'
    },
    description: {
      en: 'Synthesis of all competencies — digital public health project for a real AOF district',
      fr: 'Synthèse de toutes les compétences — projet de santé publique numérique pour un district AOF réel'
    },
    level: 4,
    status: 'locked',
    completionPercentage: 0,
    estimatedHours: 24,
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

export function getModulesByLevel(level: 1 | 2 | 3 | 4): Module[] {
  return CURRICULUM_MODULES.filter(module => module.level === level);
}

export function isModuleUnlocked(module: Module, allModules: Module[] = CURRICULUM_MODULES): boolean {
  if (module.prerequisites.length === 0) return true;

  const prerequisiteModules = allModules.filter(m =>
    module.prerequisites.includes(m.id)
  );

  return prerequisiteModules.every(prereq => prereq.status === 'completed');
}

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

export function getModuleById(moduleId: string): Module | undefined {
  return CURRICULUM_MODULES.find(module => module.id === moduleId);
}

export function getPrerequisiteModules(module: Module): Module[] {
  return CURRICULUM_MODULES.filter(m => module.prerequisites.includes(m.id));
}
